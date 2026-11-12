import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { getPlayState, startQuiz } from '../../services/playApi'
import { toApiError, errorText } from '../../services/apiError'
import { emit } from '../../telemetry/client'
import QuizPlayer from './QuizPlayer'
import H2HSection from './H2HSection'
import Leaderboard from './Leaderboard'
import { regionName } from './quizText'

const btn = 'min-h-[44px] rounded-lg bg-teal-700 px-5 py-2 text-sm font-semibold text-white disabled:opacity-60'

// The Play hub: daily quiz, packs, weekly challenge, head-to-head and the
// leaderboard. Renders nothing when Play is off for the account (403/404).
export default function QuizHub({ token }) {
  const { t, i18n } = useTranslation('play')
  const [state, setState] = useState(null) // null loading, false unavailable
  const [run, setRun] = useState(null) // {session, mode, pack}
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const load = useCallback(() => {
    getPlayState(token).then(setState, () => setState(false))
  }, [token])
  useEffect(() => { load() }, [load])
  useEffect(() => { if (state) emit('play_state_view') }, [!!state]) 
  const challengeId = state?.challenge?.id
  useEffect(() => { if (challengeId) emit('play_challenge_view') }, [challengeId])

  if (!state) return null

  async function start(body) {
    if (busy) return
    setBusy(true); setError('')
    try {
      const session = await startQuiz(token, { ...body, locale: i18n.language })
      setRun({ session, mode: body.mode, pack: body.pack })
    } catch (e) {
      setError(errorText(t, toApiError(e)))
    } finally { setBusy(false) }
  }
  const close = () => { setRun(null); load() }

  if (run) {
    return (
      <div className="space-y-4" data-tid="play.quizarea">
        <QuizPlayer token={token} session={run.session} mode={run.mode} pack={run.pack} onClose={close} />
      </div>
    )
  }

  const { daily, packs = [], challenge } = state
  const country = challenge?.country
  const countryName = country && /^[A-Za-z]{2}$/.test(country) ? regionName(country, country, i18n.language) : country
  return (
    <div className="space-y-6" data-tid="play.hub">
      <section className="rounded-2xl bg-white p-4 shadow sm:p-6" data-tid="play.daily" aria-labelledby="daily-title">
        <h2 id="daily-title" className="mb-1 text-lg font-semibold text-slate-800">{t('daily.title')}</h2>
        <p className="mb-3 text-sm text-slate-600">{t('daily.hint')}</p>
        {daily?.streak?.current > 0 && (
          <p className="mb-2 text-sm text-slate-700" data-tid="play.daily.streak">{t('daily.streak', { count: daily.streak.current })}</p>
        )}
        {daily?.done ? (
          <p className="font-semibold text-emerald-700" data-tid="play.daily.done">{t('daily.done', { count: daily.score ?? 0 })}</p>
        ) : (
          <button type="button" disabled={busy || daily?.available === false} onClick={() => start({ mode: 'daily' })}
            data-tid="play.daily.start" className={btn}>{t('daily.start')}</button>
        )}
      </section>

      {challenge && (
        <section className="rounded-2xl bg-white p-4 shadow sm:p-6" data-tid="play.challenge" aria-labelledby="challenge-title">
          <h2 id="challenge-title" className="mb-1 text-lg font-semibold text-slate-800">{t('challenge.title')}</h2>
          <p className="mb-3 text-sm text-slate-600">
            {challenge.kind === 'destination' && countryName ? t('challenge.destination', { country: countryName }) : t('challenge.featured')}
          </p>
          {challenge.done
            ? <p className="font-semibold text-emerald-700" data-tid="play.challenge.done">{t('challenge.done')}</p>
            : <button type="button" disabled={busy} onClick={() => start({ mode: 'challenge' })}
              data-tid="play.challenge.start" className={btn}>{t('challenge.start')}</button>}
        </section>
      )}

      <section className="rounded-2xl bg-white p-4 shadow sm:p-6" data-tid="play.packs" aria-labelledby="packs-title">
        <h2 id="packs-title" className="mb-3 text-lg font-semibold text-slate-800">{t('packs.title')}</h2>
        <ul className="grid grid-cols-2 gap-3">
          {packs.map((p) => (
            <li key={p.id}>
              <button type="button" disabled={busy} onClick={() => start({ mode: 'pack', pack: p.id })}
                data-tid={`play.pack.${p.id}`}
                className="min-h-[72px] w-full rounded-xl border-2 border-slate-200 bg-white px-3 py-3 text-left text-sm font-semibold text-slate-800 hover:border-teal-600 disabled:opacity-60">
                {t(`pack.${p.id}`, { defaultValue: p.id })}
              </button>
            </li>
          ))}
        </ul>
      </section>

      {error && <p role="alert" data-tid="play.error" className="text-sm text-rose-700">{error}</p>}
      <H2HSection token={token} onStart={(session, mode, pack) => setRun({ session, mode, pack })} />
      <Leaderboard token={token} />
    </div>
  )
}
