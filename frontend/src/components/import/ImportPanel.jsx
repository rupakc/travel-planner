import { useEffect, useRef, useState, useCallback } from 'react'
import { useTranslation } from 'react-i18next'
import { Link2, ImagePlus, X, Check, Loader2, AlertCircle, RotateCcw, ClipboardPaste, ScanText, Sparkles } from 'lucide-react'
import { extractImport } from '../../services/api'
import { track } from '../../utils/analytics'
import { fmtNumber } from '../../i18n/format'
import {
  IMPORT_EXAMPLES, MAX_IMAGES, MAX_UPLOAD_BASE64, detectImportInput, importErrorView, checkImageFile, prepareScreenshot,
} from '../../utils/linkImport'

const MAX_TEXT = 20000
// When each step of the story starts (ms). The request is one call, so the
// steps follow its typical timing; the last one holds until it returns.
const STEP_AT = [0, 2500, 7000]
// Measured: pasted text ~5–10 s; a long article or screenshots ~15–35 s (copy: import.typical.*)

let shotSeq = 0
const objectUrl = (file) => (typeof URL !== 'undefined' && URL.createObjectURL ? URL.createObjectURL(file) : '')
const revoke = (url) => { if (url && URL.revokeObjectURL) URL.revokeObjectURL(url) }

/**
 * The "From a link" input: one smart box for a link or pasted text, a
 * screenshot drop zone, example chips, a staged progress story, and errors
 * that offer the next step. Calls onPreview(preview) on success.
 * `seed` ({url, files, autoStart, nonce}) prefills it from a deep link or a
 * screenshot dropped anywhere on the page.
 */
export default function ImportPanel({ token, onPreview, seed = null }) {
  const { t } = useTranslation('search')
  const [text, setText] = useState('')
  const [shots, setShots] = useState([])
  const [shotErrors, setShotErrors] = useState([])
  const [busy, setBusy] = useState(null) // { kind, startedAt }
  const [step, setStep] = useState(0)
  const [elapsed, setElapsed] = useState(0)
  const [error, setError] = useState(null)
  const failedKind = useRef(null)
  const [dragging, setDragging] = useState(false)
  const textRef = useRef(null)
  const fileRef = useRef(null)
  const abortRef = useRef(null)
  const shotsRef = useRef(shots)
  shotsRef.current = shots

  useEffect(() => () => {
    abortRef.current?.abort()
    shotsRef.current.forEach((s) => revoke(s.previewUrl))
  }, [])

  const addFiles = useCallback(async (fileList) => {
    const files = [...(fileList || [])]
    if (!files.length) return
    const errors = []
    const accepted = []
    for (const file of files) {
      const problem = checkImageFile(file, { beforeShrink: true })
      if (problem) errors.push(problem)
      else accepted.push(file)
    }
    const room = MAX_IMAGES - shotsRef.current.length
    if (accepted.length > room) errors.push(t('import.tooMany', { max: MAX_IMAGES, kept: Math.max(0, room) }))
    const added = []
    for (const file of accepted.slice(0, Math.max(0, room))) {
      try {
        const payload = await prepareScreenshot(file)
        if (payload.data_base64.length > MAX_UPLOAD_BASE64) {
          errors.push(t('import.tooBig', { name: file.name || t('import.thatScreenshotCap') }))
          continue
        }
        added.push({ id: ++shotSeq, name: file.name || t('import.screenshot'), previewUrl: objectUrl(file), payload })
      } catch {
        errors.push(t('import.unreadable', { name: file.name || t('import.thatScreenshot') }))
      }
    }
    setShotErrors(errors)
    if (added.length) {
      setShots((s) => [...s, ...added].slice(0, MAX_IMAGES))
      setError(null)
    }
  }, [t])

  const removeShot = (id) => setShots((s) => {
    const gone = s.find((x) => x.id === id)
    revoke(gone?.previewUrl)
    return s.filter((x) => x.id !== id)
  })

  const detected = detectImportInput(text)
  const kind = shots.length ? 'images' : detected.kind === 'empty' ? null : detected.kind
  const tooLong = !shots.length && text.length > MAX_TEXT

  const start = useCallback(async (body, sourceKind) => {
    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller
    setError(null)
    setStep(0)
    setElapsed(0)
    setBusy({ kind: sourceKind })
    track('import_started', 'search', { kind: sourceKind })
    try {
      const preview = await extractImport(body, token, controller.signal)
      if (controller.signal.aborted) return
      onPreview(preview)
    } catch (err) {
      const view = importErrorView(err)
      if (view && !controller.signal.aborted) {
        failedKind.current = sourceKind
        setError(view)
        track('import_failed', 'search', { code: view.code })
      }
    } finally {
      if (abortRef.current === controller) {
        abortRef.current = null
        setBusy(null)
      }
    }
  }, [token, onPreview])

  const submit = (e) => {
    e?.preventDefault()
    if (!kind || tooLong || busy) return
    if (kind === 'images') start({ images: shots.map((s) => s.payload) }, 'images')
    else if (kind === 'url') start({ url: detected.url }, 'url')
    else start({ text: text.trim() }, 'text')
  }

  const cancel = useCallback(() => {
    abortRef.current?.abort()
    abortRef.current = null
    setBusy(null)
    setTimeout(() => textRef.current?.focus(), 0)
  }, [])

  // The story: step through as time passes, and tick the elapsed seconds
  useEffect(() => {
    if (!busy) return undefined
    const began = Date.now()
    const timers = STEP_AT.slice(1).map((at, i) => setTimeout(() => setStep(i + 1), at))
    const tick = setInterval(() => setElapsed(Math.round((Date.now() - began) / 1000)), 1000)
    const onKey = (e) => { if (e.key === 'Escape') cancel() }
    document.addEventListener('keydown', onKey)
    return () => {
      timers.forEach(clearTimeout)
      clearInterval(tick)
      document.removeEventListener('keydown', onKey)
    }
  }, [busy, cancel])

  // Deep link / page-level drop
  useEffect(() => {
    if (!seed) return
    if (seed.files?.length) addFiles(seed.files)
    if (seed.url) {
      setText(seed.url)
      if (seed.autoStart) start({ url: seed.url }, 'url')
    }
  }, [seed?.nonce])

  const runAction = (action) => {
    setError(null)
    if (action === 'text') {
      // A failed link makes room for its text; pasted text is kept to trim
      if (failedKind.current === 'url') setText('')
      setShots([])
      textRef.current?.focus()
    } else if (action === 'images') {
      fileRef.current?.click()
    } else if (action === 'retry') {
      submit()
    }
  }

  const onPaste = (e) => {
    const files = [...(e.clipboardData?.files || [])].filter((f) => f.type.startsWith('image/') || /\.hei[cf]$/i.test(f.name))
    if (files.length) {
      e.preventDefault()
      addFiles(files)
    }
  }

  if (busy) {
    const steps = [t(`import.steps.${busy.kind}`), t('import.steps.find'), t('import.steps.map')]
    return (
      <div className="space-y-5">
        <div className="rounded-2xl border border-amber-200 bg-amber-50/60 p-5 sm:p-6">
          <ol className="space-y-3" aria-hidden="true">
            {steps.map((label, i) => {
              const done = i < step
              const active = i === step
              return (
                <li key={label} className="flex items-center gap-3">
                  <span className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-xs font-bold transition-colors ${
                    done ? 'bg-teal-600 text-white' : active ? 'bg-amber-400 text-amber-950 import-step-active' : 'bg-white text-gray-400 ring-1 ring-gray-200'
                  }`}>
                    {done ? <Check size={14} /> : i + 1}
                  </span>
                  <span className={`text-sm sm:text-base ${active ? 'font-semibold text-gray-900' : done ? 'text-gray-600' : 'text-gray-400'}`}>
                    {label}{active ? '…' : ''}
                  </span>
                </li>
              )
            })}
          </ol>
          <p className="sr-only" aria-live="polite">{steps[step]}…</p>
          <div className="mt-5 flex flex-wrap items-center justify-between gap-3 border-t border-amber-200/70 pt-4">
            <p className="text-xs text-amber-900/80 tabular-nums">{t(`import.typical.${busy.kind}`)}{elapsed > 0 ? t('import.elapsed', { seconds: elapsed }) : ''}</p>
            <button type="button" onClick={cancel} data-tid="search.import-cancel"
              className="rounded-lg px-3 py-1.5 text-sm font-medium text-amber-900 hover:bg-amber-100 focus:outline-none focus-visible:ring-2 focus-visible:ring-amber-500">
              {t('import.cancel')} <span className="text-amber-900/50 text-xs">{t('import.escKey')}</span>
            </button>
          </div>
        </div>
        <div className="space-y-2" aria-hidden="true">
          {[0, 1, 2].map((i) => (
            <div key={i} className="flex items-center gap-3 rounded-xl border border-gray-100 p-3">
              <div className="skeleton-shimmer h-8 w-8 rounded-full" />
              <div className="flex-1 space-y-1.5">
                <div className="skeleton-shimmer h-3 rounded" style={{ width: `${60 - i * 12}%` }} />
                <div className="skeleton-shimmer h-2.5 rounded" style={{ width: `${40 + i * 10}%` }} />
              </div>
            </div>
          ))}
        </div>
      </div>
    )
  }

  return (
    <form onSubmit={submit} onPaste={onPaste} className="space-y-4" aria-label={t('import.formAria')}>
      <div>
        <label htmlFor="import-input" className="block text-sm font-medium text-gray-700 mb-1">
          {t('import.pasteLabel')}
        </label>
        <textarea
          id="import-input"
          ref={textRef}
          value={text}
          onChange={(e) => { setText(e.target.value); setError(null) }}
          onKeyDown={(e) => {
            const isLink = detectImportInput(e.currentTarget.value).kind === 'url'
            if (e.key === 'Enter' && (e.metaKey || e.ctrlKey || (isLink && !e.shiftKey))) submit(e)
          }}
          rows={4}
          disabled={shots.length > 0}
          placeholder={t('import.placeholder')}
          className="w-full resize-y rounded-xl border border-gray-200 bg-white px-3.5 py-3 text-sm leading-relaxed focus:border-amber-400 focus:outline-none focus:ring-2 focus:ring-amber-300 disabled:bg-gray-50 disabled:text-gray-400"
        />
        <div className="mt-1 flex min-h-[1.25rem] items-center justify-between gap-2 text-xs">
          <span className="flex items-center gap-1.5 text-gray-500">
            {shots.length > 0 ? (
              <>{t('import.shotsNote', { count: shots.length })}</>
            ) : detected.kind === 'url' ? (
              <><Link2 size={12} className="text-amber-600" /> {t('import.detectedUrl')}</>
            ) : detected.kind === 'text' ? (
              <><ScanText size={12} className="text-amber-600" /> {t('import.detectedText')}</>
            ) : null}
          </span>
          {!shots.length && text.length > 400 && (
            <span className={`tabular-nums ${tooLong ? 'font-semibold text-rose-600' : 'text-gray-400'}`}>
              {t('import.counter', { n: fmtNumber(text.length), max: fmtNumber(MAX_TEXT) })}
            </span>
          )}
        </div>
      </div>

      {/* Screenshot drop zone */}
      <div
        onDragOver={(e) => { e.preventDefault(); setDragging(true) }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => { e.preventDefault(); setDragging(false); addFiles(e.dataTransfer?.files) }}
        className={`rounded-xl border-2 border-dashed p-3 transition-colors ${dragging ? 'border-amber-400 bg-amber-50' : 'border-gray-200'}`}
      >
        <input ref={fileRef} type="file" accept="image/png,image/jpeg,image/webp,image/gif,.heic,.heif" multiple className="sr-only"
          aria-label={t('import.chooseAria')} tabIndex={-1} data-tid="search.import-file-input"
          onChange={(e) => { addFiles(e.target.files); e.target.value = '' }} />
        <div className="flex flex-wrap items-center gap-3">
          {shots.map((s) => (
            <div key={s.id} data-shot className="relative h-16 w-16 overflow-hidden rounded-lg ring-1 ring-gray-200 bg-gray-50">
              {s.previewUrl && <img src={s.previewUrl} alt={s.name} className="h-full w-full object-cover" />}
              <button type="button" onClick={() => removeShot(s.id)} aria-label={t('import.removeShot', { name: s.name })} data-tid="search.import-shot-remove"
                className="absolute right-0.5 top-0.5 rounded-full bg-gray-900/70 p-0.5 text-white hover:bg-gray-900 focus:outline-none focus-visible:ring-2 focus-visible:ring-amber-400">
                <X size={12} />
              </button>
            </div>
          ))}
          {shots.length < MAX_IMAGES && (
            <button type="button" onClick={() => fileRef.current?.click()} data-tid="search.import-choose-files"
              className="flex items-center gap-2 rounded-lg px-2 py-1.5 text-sm text-gray-600 hover:bg-gray-50 hover:text-gray-900 focus:outline-none focus-visible:ring-2 focus-visible:ring-amber-400">
              <ImagePlus size={18} className="text-amber-600" />
              <span>{shots.length ? t('import.addAnother') : <>{t('import.dropLead')} <span className="font-medium text-amber-700 underline underline-offset-2">{t('import.chooseFiles')}</span></>}</span>
            </button>
          )}
          <span className="ml-auto hidden text-xs text-gray-400 sm:inline">
            <ClipboardPaste size={12} className="mr-1 inline" />{t('import.dropHint', { max: MAX_IMAGES })}
          </span>
        </div>
        {shotErrors.length > 0 && (
          <ul className="mt-2 space-y-0.5 text-xs text-rose-700">
            {shotErrors.map((m, i) => <li key={i}>{m}</li>)}
          </ul>
        )}
      </div>

      {error && (
        <div role="alert" className="flex flex-col gap-3 rounded-xl border border-rose-200 bg-rose-50 p-3.5 sm:flex-row sm:items-center">
          <p className="flex flex-1 items-start gap-2 text-sm text-rose-800">
            <AlertCircle size={16} className="mt-0.5 shrink-0" />{error.message}
          </p>
          {error.actions.length > 0 && (
            <div className="flex shrink-0 flex-wrap gap-2">
              {error.actions.includes('text') && (
                <button type="button" onClick={() => runAction('text')} data-tid="search.import-action-text"
                  className="rounded-lg bg-white px-3 py-1.5 text-sm font-medium text-rose-800 ring-1 ring-rose-200 hover:bg-rose-100">
                  {t('import.actions.text')}
                </button>
              )}
              {error.actions.includes('images') && (
                <button type="button" onClick={() => runAction('images')} data-tid="search.import-action-images"
                  className="rounded-lg bg-white px-3 py-1.5 text-sm font-medium text-rose-800 ring-1 ring-rose-200 hover:bg-rose-100">
                  {t('import.actions.images')}
                </button>
              )}
              {error.actions.includes('retry') && (
                <button type="button" onClick={() => runAction('retry')} data-tid="search.import-action-retry"
                  className="flex items-center gap-1 rounded-lg bg-white px-3 py-1.5 text-sm font-medium text-rose-800 ring-1 ring-rose-200 hover:bg-rose-100">
                  <RotateCcw size={13} /> {t('import.actions.retry')}
                </button>
              )}
            </div>
          )}
        </div>
      )}

      <div className="flex flex-wrap items-center gap-2">
        <span className="text-xs text-gray-500">{t('import.examples')}</span>
        {IMPORT_EXAMPLES.map((ex) => (
          <button key={ex.label} type="button" data-tid="search.import-example"
            onClick={() => { setShots([]); setText(ex.text); setError(null); textRef.current?.focus() }}
            className="rounded-full border border-amber-200 bg-amber-50 px-3 py-1 text-xs font-medium text-amber-900 hover:bg-amber-100 focus:outline-none focus-visible:ring-2 focus-visible:ring-amber-400">
            {ex.label}
          </button>
        ))}
      </div>

      <button type="submit" disabled={!kind || tooLong} data-tid="search.import-submit"
        className="flex w-full items-center justify-center gap-2 rounded-xl bg-gradient-to-r from-teal-600 to-teal-700 px-6 py-3.5 text-base font-semibold text-white shadow-lg transition-all hover:from-teal-700 hover:to-teal-800 hover:shadow-xl active:scale-[0.99] disabled:cursor-not-allowed disabled:opacity-50 disabled:shadow-none">
        {busy ? <Loader2 size={18} className="animate-spin" /> : <Sparkles size={18} />}
        {kind === 'images' ? t('import.findInShots', { count: shots.length }) : t('import.find')}
      </button>
    </form>
  )
}
