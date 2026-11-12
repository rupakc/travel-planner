import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useNavigate } from 'react-router-dom'
import { getH2H, acceptH2H, declineH2H } from '../../services/playApi'
import { toApiError, errorText } from '../../services/apiError'
import { emit } from '../../telemetry/client'
import QuizPlayer from './QuizPlayer'

const btn = 'min-h-[44px] rounded-lg px-5 py-2 text-sm font-semibold'

// /play/h2h/:id: accept or decline, play, or see the result of one match.
export default function H2HMatch({ token, id }) {
  const { t } = useTranslation('play')
  const navigate = useNavigate()
  const [match, setMatch] = useState(undefined) // undefined loading, null not found
  const [run, setRun] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const opened = useRef(false)

  const load = () => getH2H(token).then(
    (d) => setMatch((d?.matches || []).find((m) => String(m.id) === String(id)) || null),
    () => setMatch(null),
  )
  useEffect(() => { load() }, [token, id]) 
  useEffect(() => {
    if (match && !opened.current) { opened.current = true; emit('play_h2h_open') }
    if (match?.state === 'done' && match.winner) emit('play_h2h_result', { winner: match.winner })
  }, [match])

  async function accept() {
    setBusy(true); setError('')
    try {
      const session = await acceptH2H(token, id)
      setRun({ ...session, answers: session.answers || [] })
    } catch (e) { setError(errorText(t, toApiError(e))) } finally { setBusy(false) }
  }
  async function decline() {
    setBusy(true); setError('')
    try { await declineH2H(token, id); navigate('/play') } catch (e) {
      setError(errorText(t, toApiError(e))); setBusy(false)
    }
  }

  const back = <Link to="/play" data-tid="play.h2h.back" className="inline-flex min-h-[44px] items-center text-sm font-semibold text-teal-700 underline">{t('h2h.back')}</Link>
  if (run) {
    return <QuizPlayer token={token} session={run} mode="h2h" onClose={() => { setRun(null); load() }} />
  }
  if (match === undefined) return <p className="text-sm text-slate-500" role="status">{t('loading')}</p>
  if (match === null) {
    return <div data-tid="play.h2h.missing"><p className="text-sm text-slate-600">{t('h2h.missing')}</p>{back}</div>
  }
  return (
    <section className="rounded-2xl bg-white p-4 shadow sm:p-6" data-tid="play.h2h.match" aria-labelledby="match-title">
      <h2 id="match-title" className="mb-1 text-lg font-semibold text-slate-800">
        {t('h2h.vs', { handle: match.opponent?.handle })}
      </h2>
      <p className="mb-3 text-sm text-slate-600" data-tid="play.h2h.state">{t(`h2h.state_${match.state}`)}</p>
      {match.state === 'done' && (
        <div data-tid="play.h2h.result">
          <p className="text-2xl font-bold text-teal-700">{t('h2h.score', { you: match.you ?? 0, them: match.them ?? 0 })}</p>
          <p className="font-semibold text-slate-800" data-tid="play.h2h.winner">{t(`h2h.winner_${match.winner || 'draw'}`)}</p>
        </div>
      )}
      {match.state === 'waiting_you' && (
        <div className="flex flex-wrap gap-3">
          <button type="button" disabled={busy} onClick={accept} data-tid="play.h2h.accept" className={`${btn} bg-teal-700 text-white`}>{t('h2h.accept')}</button>
          <button type="button" disabled={busy} onClick={decline} data-tid="play.h2h.decline" className={`${btn} border border-slate-300 text-slate-700`}>{t('h2h.decline')}</button>
        </div>
      )}
      {error && <p role="alert" data-tid="play.h2h.error" className="mt-2 text-sm text-rose-700">{error}</p>}
      <div className="mt-3">{back}</div>
    </section>
  )
}
