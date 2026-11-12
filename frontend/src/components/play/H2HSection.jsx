import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router-dom'
import { getH2H, createH2H } from '../../services/playApi'
import { toApiError, errorText } from '../../services/apiError'
import { emit } from '../../telemetry/client'

export const PACKS = ['flags', 'capitals', 'landmarks', 'cuisine']

export function MatchRow({ m, onOpen }) {
  const { t } = useTranslation('play')
  const score = m.state === 'done' && m.winner
    ? t('h2h.score', { you: m.you ?? 0, them: m.them ?? 0 }) : ''
  return (
    <li className="flex items-center justify-between gap-3 py-2 text-sm text-slate-700">
      <span>
        <span className="font-semibold">{m.opponent?.handle}</span>{' '}
        <span className="text-slate-500">{t(`h2h.state_${m.state}`)} {score}</span>
      </span>
      <button type="button" onClick={() => onOpen(m)} data-tid="play.h2h.open"
        className="min-h-[44px] rounded-lg border border-slate-300 px-4 py-2 text-sm font-semibold text-slate-700">{t('h2h.open')}</button>
    </li>
  )
}

// Head-to-head: open matches and a create form. `onStart(session)` begins the
// creator's quiz at once. Hidden when the backend has no head-to-head yet.
export default function H2HSection({ token, onStart }) {
  const { t } = useTranslation('play')
  const navigate = useNavigate()
  const [matches, setMatches] = useState(null)
  const [handle, setHandle] = useState('')
  const [pack, setPack] = useState('flags')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    let live = true
    getH2H(token).then((d) => { if (live) setMatches(d?.matches || []) }, () => { if (live) setMatches(false) })
    return () => { live = false }
  }, [token])
  if (matches === false || matches === null) return null

  async function create(e) {
    e.preventDefault()
    if (busy || !handle.trim()) return
    setBusy(true); setError('')
    try {
      const r = await createH2H(token, { handle: handle.trim().replace(/^@/, ''), pack })
      emit('play_h2h_create')
      onStart({ session_id: r.session_id, questions: r.questions, answers: [] }, 'h2h', pack)
    } catch (err) {
      setError(errorText(t, toApiError(err)))
    } finally { setBusy(false) }
  }

  return (
    <section className="rounded-2xl bg-white p-4 shadow sm:p-6" data-tid="play.h2h" aria-labelledby="h2h-title">
      <h2 id="h2h-title" className="mb-1 text-lg font-semibold text-slate-800">{t('h2h.title')}</h2>
      <p className="mb-3 text-sm text-slate-600">{t('h2h.hint')}</p>
      {matches.length === 0
        ? <p className="mb-3 text-sm text-slate-500" data-tid="play.h2h.empty">{t('h2h.empty')}</p>
        : (
          <ul className="mb-3 divide-y divide-slate-100" data-tid="play.h2h.list">
            {matches.map((m) => <MatchRow key={m.id} m={m} onOpen={(x) => navigate(`/play/h2h/${x.id}`)} />)}
          </ul>
        )}
      <form onSubmit={create} className="flex flex-wrap items-end gap-3" data-tid="play.h2h.form">
        <label className="block text-sm font-medium text-slate-700">
          {t('h2h.handle')}
          <input value={handle} maxLength={30} autoCapitalize="none" autoComplete="off" onChange={(e) => setHandle(e.target.value)}
            data-tid="play.h2h.handle" className="mt-1 block min-h-[44px] w-44 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-800" />
        </label>
        <label className="block text-sm font-medium text-slate-700">
          {t('h2h.pack')}
          <select value={pack} onChange={(e) => setPack(e.target.value)} data-tid="play.h2h.pack"
            className="mt-1 block min-h-[44px] rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-800">
            {PACKS.map((p) => <option key={p} value={p}>{t(`pack.${p}`)}</option>)}
          </select>
        </label>
        <button type="submit" disabled={busy || !handle.trim()} data-tid="play.h2h.create"
          className="min-h-[44px] rounded-lg bg-teal-700 px-5 py-2 text-sm font-semibold text-white disabled:opacity-60">{t('h2h.create')}</button>
      </form>
      {error && <p role="alert" data-tid="play.h2h.error" className="mt-2 text-sm text-rose-700">{error}</p>}
    </section>
  )
}
