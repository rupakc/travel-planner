import { useCallback, useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useAuth } from '../../context/AuthContext'
import { createShare, listShares, revokeShare } from '../../services/api'
import {
  DEFAULT_OPTIONS, DATES_MODES, buildIntent, canNativeShare, cardUrl, copyText, downloadBlob, pageUrl, shareFiles,
} from '../../utils/share'

function emit(event, props) {
  import('../../telemetry/client').then((m) => m.emit(event, props)).catch(() => {})
}

const FOCUSABLE = 'a[href],button:not([disabled]),input:not([disabled]),select:not([disabled]),textarea:not([disabled]),[tabindex]:not([tabindex="-1"])'
const INTENTS = ['x', 'facebook', 'whatsapp', 'linkedin']
const btn = 'min-h-[44px] rounded-lg border border-border px-3 text-sm text-text hover:bg-surface disabled:opacity-60'

/**
 * Share dialog for the Phase 4 share links (call it only when sharingEnabled(config)).
 * Props: kind ('plan'|'recap'|'savings'|'quiz'|'status'), planId (required for plan and recap, optional for status),
 * sessionId (required for quiz: the caller's finished quiz session),
 * onClose, onChange?(share | null) called after a create/update (share) or a revoke (null),
 * defaultOptions? ({dates, show_origin, show_name}), text? (share message; default is translated per kind).
 * Escape closes only this dialog and Tab stays inside it.
 */
export default function ShareDialog({ kind, planId, sessionId, onClose, onChange, defaultOptions, text }) {
  const { t } = useTranslation('share')
  const { token } = useAuth()
  const dialogRef = useRef(null)
  const urlRef = useRef(null)
  const [options, setOptions] = useState({ ...DEFAULT_OPTIONS, ...(defaultOptions || {}) })
  const [share, setShare] = useState(null)
  const [busy, setBusy] = useState(false)
  const [status, setStatus] = useState(null) // {kind: 'ok'|'error', key}
  const [confirmRevoke, setConfirmRevoke] = useState(false)
  const [imgOk, setImgOk] = useState(true)
  const dirty = useRef(false)
  const planKind = kind === 'plan' || kind === 'recap' // shows dates/origin and needs a plan
  const matchPlan = planKind
  const message = text || t(`text.${kind}`, { defaultValue: '' })
  const link = share ? (share.url || pageUrl(share.token)) : ''

  useEffect(() => { emit('share_open', { kind }) }, [kind])

  // Return focus to whatever opened the dialog when it closes
  useEffect(() => {
    const opener = document.activeElement
    return () => { if (opener && opener !== document.body && opener.isConnected) opener.focus?.() }
  }, [])

  // Pre-load the caller's existing share for this kind/plan so Create updates it
  // knowingly. The list only helps when its rows carry plan_id; any failure is ignored.
  useEffect(() => {
    let live = true
    ;(async () => {
      try {
        const d = await listShares(token)
        const rows = Array.isArray(d?.shares) ? d.shares : []
        const hit = kind === 'quiz' ? null : rows.find((s) => s.kind === kind && (!matchPlan || (s.plan_id != null && String(s.plan_id) === String(planId))))
        if (!live || !hit) return
        setShare(hit)
        if (!dirty.current) setOptions((o) => ({ ...o, ...(hit.options || {}) }))
      } catch { /* continue without it */ }
    })()
    return () => { live = false }
  }, [token, kind, planId, matchPlan])

  useEffect(() => {
    dialogRef.current?.focus()
    const onKey = (e) => {
      if (e.key === 'Escape') {
        e.stopPropagation(); e.preventDefault(); onClose?.()
        return
      }
      if (e.key !== 'Tab' || !dialogRef.current) return
      const items = [...dialogRef.current.querySelectorAll(FOCUSABLE)]
      if (!items.length) return
      const first = items[0]; const last = items[items.length - 1]
      const active = document.activeElement
      if (e.shiftKey && (active === first || active === dialogRef.current)) { e.preventDefault(); last.focus() }
      else if (!e.shiftKey && active === last) { e.preventDefault(); first.focus() }
    }
    window.addEventListener('keydown', onKey, true)
    return () => window.removeEventListener('keydown', onKey, true)
  }, [onClose])

  const ok = (key) => setStatus({ kind: 'ok', key })
  const fail = (key) => setStatus({ kind: 'error', key })

  const submit = async () => {
    setBusy(true); setStatus(null)
    try {
      const body = { kind, options }
      if (planKind || (kind === 'status' && planId != null)) body.plan_id = planId
      if (kind === 'quiz') body.session_id = sessionId
      const res = await createShare(token, body)
      const wasNew = !share
      setShare(res); setImgOk(true)
      emit('share_create', { kind, dates: options.dates })
      ok(wasNew ? 'created' : 'updated')
      onChange?.(res)
    } catch (e) {
      const st = e?.response?.status
      const code = e?.response?.data?.error_code || e?.response?.data?.detail?.error_code || e?.response?.data?.code
      fail(st === 404 || (st === 422 && code === 'invalid_kind') ? 'unavailable' : code === 'no_active_trip' ? 'noActiveTrip' : 'create')
    } finally { setBusy(false) }
  }

  const act = useCallback(async (target) => {
    if (!share) return
    setStatus(null)
    const done = (key) => { emit('share_action', { kind, target }); ok(key) }
    try {
      if (target === 'copy') {
        if (await copyText(link)) done('copy')
        else { urlRef.current?.focus(); urlRef.current?.select?.(); ok('copyFailed') }
      } else if (target === 'native') {
        let blob = null
        try { blob = await (await fetch(share.card_url?.link || cardUrl(share.token))).blob() } catch { /* link only */ }
        if (await shareFiles({ blob, url: link, text: message })) done('native')
      } else if (target === 'download' || target === 'downloadStory') {
        const size = target === 'download' ? 'link' : 'story'
        const r = await fetch(share.card_url?.[size] || cardUrl(share.token, size))
        if (!r.ok) throw new Error('card')
        downloadBlob(await r.blob(), `voyager-${kind}-${size}.png`)
        emit('share_action', { kind, target: 'download' }); ok('download')
      } else {
        const href = buildIntent(target, { url: link, text: message })
        if (href) { window.open(href, '_blank', 'noopener,noreferrer'); done('opened') }
      }
    } catch (e) {
      fail(target === 'download' || target === 'downloadStory' ? 'download' : 'share')
    }
  }, [share, link, kind, message])

  const doRevoke = async () => {
    setBusy(true)
    try {
      await revokeShare(token, share.token)
      emit('share_revoke', { kind })
      setShare(null); setConfirmRevoke(false); ok('revoked')
      onChange?.(null)
    } catch { fail('revoke') } finally { setBusy(false) }
  }

  const set = (patch) => { dirty.current = true; setOptions((o) => ({ ...o, ...patch })) }
  const check = 'h-5 w-5 shrink-0 rounded border-border text-teal-700 focus:ring-teal-600'

  return (
    <div className="fixed inset-0 z-[80] flex items-end justify-center bg-black/50 p-0 sm:items-center sm:p-4" data-tid="share-backdrop"
      onClick={(e) => { if (e.target === e.currentTarget) onClose?.() }}>
      <div ref={dialogRef} role="dialog" aria-modal="true" aria-labelledby="share-title" tabIndex={-1}
        data-tid="share-dialog"
        className="max-h-[92vh] w-full max-w-md space-y-3 overflow-y-auto rounded-t-2xl bg-surface-raised p-4 shadow-xl text-text outline-none sm:rounded-2xl">
        <h2 id="share-title" className="text-base font-semibold text-text">{t(`titleKind.${kind}`, { defaultValue: t('title') })}</h2>
        <p className="text-sm text-text">{t('intro')}</p>
        {planKind && <p className="text-xs text-text-muted">{t('reveals')}</p>}

        <fieldset className="space-y-2" disabled={busy}>
          <legend className="text-sm font-medium text-text">{t('optionsLegend')}</legend>
          {planKind && (
            <div>
              <label htmlFor="share-dates" className="block text-xs text-text-muted">{t('dates')}</label>
              <select id="share-dates" data-tid="share-dates" value={options.dates} onChange={(e) => set({ dates: e.target.value })}
                className="mt-1 min-h-[44px] w-full rounded-lg border border-border bg-surface-raised px-2 text-sm text-text">
                {DATES_MODES.map((m) => <option key={m} value={m}>{t(`dates${m[0].toUpperCase()}${m.slice(1)}`)}</option>)}
              </select>
              <p className="mt-1 text-xs text-text-muted">{t('datesNote')}</p>
            </div>
          )}
          {planKind && (
            <label className="flex min-h-[44px] items-center gap-3 text-sm text-text">
              <input type="checkbox" className={check} data-tid="share-origin" checked={options.show_origin}
                onChange={(e) => set({ show_origin: e.target.checked })} />
              {t('showOrigin')}
            </label>
          )}
          <label className="flex min-h-[44px] items-center gap-3 text-sm text-text">
            <input type="checkbox" className={check} data-tid="share-name" checked={options.show_name}
              onChange={(e) => set({ show_name: e.target.checked })} />
            {t('showName')}
          </label>
        </fieldset>

        <button type="button" data-tid="share-create" onClick={submit} disabled={busy}
          className="min-h-[44px] w-full rounded-lg bg-teal-700 px-4 text-sm font-semibold text-white hover:bg-teal-800 disabled:opacity-60">
          {busy ? t('working') : share ? t('update') : t('create')}
        </button>

        {share && (
          <div className="space-y-3">
            {imgOk && (
              <img src={share.card_url?.link || cardUrl(share.token)} alt={t('preview')} onError={() => setImgOk(false)}
                className="aspect-[1200/630] w-full rounded-xl border border-border object-cover" />
            )}
            <div>
              <label htmlFor="share-url" className="block text-xs text-text-muted">{t('urlLabel')}</label>
              <input id="share-url" ref={urlRef} readOnly value={link} onFocus={(e) => e.target.select()} data-tid="share-url"
                className="mt-1 min-h-[44px] w-full rounded-lg border border-border bg-surface-raised px-2 text-sm text-text" />
            </div>
            <div className="flex flex-wrap gap-2">
              {canNativeShare() && <button type="button" data-tid="share-native" className={btn} onClick={() => act('native')}>{t('actions.native')}</button>}
              <button type="button" data-tid="share-copy" className={btn} onClick={() => act('copy')}>{t('actions.copy')}</button>
              <button type="button" data-tid="share-download" className={btn} onClick={() => act('download')}>{t('actions.download')}</button>
              <button type="button" data-tid="share-download-story" className={btn} onClick={() => act('downloadStory')}>{t('actions.downloadStory')}</button>
            </div>
            <div role="group" aria-label={t('actionsLabel')} className="flex flex-wrap gap-2">
              {INTENTS.map((k) => (
                <button key={k} type="button" data-tid={`share-${k}`} className={btn} onClick={() => act(k)}>{t(`actions.${k}`)}</button>
              ))}
            </div>
            {confirmRevoke ? (
              <div role="alertdialog" aria-label={t('revokeConfirm')} className="space-y-2 rounded-lg border border-red-200 p-3">
                <p className="text-sm text-text">{t('revokeConfirm')}</p>
                <div className="flex gap-2">
                  <button type="button" data-tid="share-revoke-yes" onClick={doRevoke} disabled={busy}
                    className="min-h-[44px] rounded-lg bg-red-700 px-3 text-sm font-semibold text-white disabled:opacity-60">{t('revokeYes')}</button>
                  <button type="button" data-tid="share-revoke-no" onClick={() => setConfirmRevoke(false)} className={btn}>{t('revokeNo')}</button>
                </div>
              </div>
            ) : (
              <button type="button" data-tid="share-revoke" onClick={() => setConfirmRevoke(true)}
                className="min-h-[44px] text-sm text-red-700 underline">{t('revoke')}</button>
            )}
          </div>
        )}

        <p role="status" aria-live="polite" data-testid="share-status" className="text-xs text-text-muted">
          {status?.kind === 'ok' ? t(`status.${status.key}`) : ''}
        </p>
        <p role="alert" data-testid="share-error" className="text-xs text-red-700">
          {status?.kind === 'error' ? t(`errors.${status.key}`) : ''}
        </p>

        <button type="button" data-tid="share-close" onClick={onClose}
          className="min-h-[44px] w-full rounded-lg border border-border px-4 text-sm text-text">{t('close')}</button>
      </div>
    </div>
  )
}
