import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { getLeaderboard, getSocialProfile, saveSocialProfile } from '../../services/playApi'
import { toApiError, errorText } from '../../services/apiError'
import { emit } from '../../telemetry/client'

const SCOPES = ['global', 'friends']
const WEEKS = ['current', 'previous']

function OptIn({ token, onJoined }) {
  const { t } = useTranslation('play')
  const [handle, setHandle] = useState('')
  const [needsHandle, setNeedsHandle] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  useEffect(() => {
    let live = true
    getSocialProfile(token).then((p) => { if (live) setNeedsHandle(!p?.handle) }, () => {})
    return () => { live = false }
  }, [token])

  async function join(e) {
    e.preventDefault()
    if (busy || (needsHandle && !handle.trim())) return
    setBusy(true); setError('')
    try {
      await saveSocialProfile(token, needsHandle
        ? { handle: handle.trim(), leaderboard_opt_in: true } : { leaderboard_opt_in: true })
      onJoined()
    } catch (err) {
      setError(errorText(t, toApiError(err)))
    } finally { setBusy(false) }
  }
  return (
    <form onSubmit={join} className="rounded-xl border border-slate-200 bg-slate-50 p-4" data-tid="play.board.optin">
      <p className="mb-2 text-sm text-slate-700">{t('board.optinNote')}</p>
      {needsHandle && (
        <label className="mb-2 block text-sm font-medium text-slate-700">
          {t('board.handle')}
          <input value={handle} maxLength={30} autoCapitalize="none" autoComplete="off" onChange={(e) => setHandle(e.target.value)}
            data-tid="play.board.handle" className="mt-1 block min-h-[44px] w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-800" />
        </label>
      )}
      <button type="submit" disabled={busy} data-tid="play.board.join"
        className="min-h-[44px] rounded-lg bg-teal-700 px-5 py-2 text-sm font-semibold text-white disabled:opacity-60">{t('board.join')}</button>
      {error && <p role="alert" className="mt-2 text-sm text-rose-700" data-tid="play.board.error">{error}</p>}
    </form>
  )
}

// This week's board (global opt-in or friends), handles only.
export default function Leaderboard({ token }) {
  const { t } = useTranslation('play')
  const [scope, setScope] = useState('friends')
  const [week, setWeek] = useState('current')
  const [data, setData] = useState(null)
  const [failed, setFailed] = useState(false)

  const load = useCallback(() => {
    let live = true
    setData(null); setFailed(false)
    getLeaderboard(token, scope, week).then((d) => { if (live) setData(d) }, () => { if (live) setFailed(true) })
    return () => { live = false }
  }, [token, scope, week])
  useEffect(() => load(), [load])
  useEffect(() => { emit('play_board_view', { scope }) }, [scope])

  const rows = data?.rows || []
  const tab = (active) => `min-h-[44px] rounded-lg px-4 py-2 text-sm font-semibold ${active ? 'bg-teal-700 text-white' : 'bg-slate-100 text-slate-700'}`
  return (
    <section className="rounded-2xl bg-white p-4 shadow sm:p-6" data-tid="play.board" aria-labelledby="board-title">
      <h2 id="board-title" className="mb-3 text-lg font-semibold text-slate-800">{t('board.title')}</h2>
      <div className="mb-2 flex flex-wrap gap-2" role="tablist" aria-label={t('board.scope')}>
        {SCOPES.map((s) => (
          <button key={s} type="button" role="tab" aria-selected={scope === s} onClick={() => setScope(s)}
            data-tid={`play.board.scope.${s}`} className={tab(scope === s)}>{t(`board.scope_${s}`)}</button>
        ))}
      </div>
      <div className="mb-3 flex gap-2">
        {WEEKS.map((w) => (
          <button key={w} type="button" aria-pressed={week === w} onClick={() => setWeek(w)}
            data-tid={`play.board.week.${w}`} className={tab(week === w)}>{t(`board.week_${w}`)}</button>
        ))}
      </div>
      {failed && <p className="text-sm text-slate-600" data-tid="play.board.failed">{t('board.failed')}</p>}
      {!failed && !data && <p className="text-sm text-slate-500" role="status">{t('loading')}</p>}
      {data && (
        <>
          {scope === 'global' && data.you && !data.you.opted_in && <OptIn token={token} onJoined={load} />}
          {rows.length === 0 && <p className="text-sm text-slate-600" data-tid="play.board.empty">{t('board.empty')}</p>}
          <ol className="divide-y divide-slate-100" data-tid="play.board.rows">
            {rows.map((r) => (
              <li key={`${r.rank}-${r.handle}`} data-tid={r.you ? 'play.board.row.you' : 'play.board.row'}
                className={`flex items-center justify-between gap-3 py-2 text-sm ${r.you ? 'font-semibold text-teal-800' : 'text-slate-700'}`}>
                <span>{r.rank}. {r.handle}{r.you ? ` ${t('board.you')}` : ''}</span>
                <span>{t('board.points', { count: r.score })}</span>
              </li>
            ))}
          </ol>
          {data.you && data.you.opted_in && data.you.rank == null && (
            <p className="mt-2 text-xs text-slate-500" data-tid="play.board.unranked">{t('board.unranked')}</p>
          )}
          {data.you && data.you.opted_in && data.you.rank != null && (
            <p className="mt-2 text-xs text-slate-500" data-tid="play.board.mine">
              {t('board.mine', { rank: data.you.rank, count: data.you.score })}
            </p>
          )}
        </>
      )}
    </section>
  )
}
