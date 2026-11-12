import { useTranslation } from 'react-i18next'
import { xpEarned } from './quizText'

// Result of a finished quiz: score, XP and streak. The marked seam
// below is where T10's share button goes.
export default function QuizResult({ summary, onClose, closeLabel }) {
  const { t } = useTranslation('play')
  const xp = xpEarned(summary)
  const streak = summary?.streak
  return (
    <section className="rounded-2xl bg-white p-6 text-center shadow" data-tid="play.result" aria-labelledby="result-title">
      <h2 id="result-title" className="mb-1 text-lg font-semibold text-slate-800">{t('result.title')}</h2>
      <p className="text-4xl font-bold text-teal-700" data-tid="play.result.score">{summary?.score ?? 0}</p>
      <p className="text-sm text-slate-600" data-tid="play.result.correct">
        {t('result.correct', { correct: summary?.correct ?? 0, total: summary?.total ?? 5 })}
      </p>
      {xp > 0 && <p className="mt-2 font-semibold text-emerald-700" data-tid="play.result.xp">{t('result.xp', { count: xp })}</p>}
      {streak?.current > 0 && (
        <p className="text-sm text-slate-600" data-tid="play.result.streak">{t('result.streak', { count: streak.current })}</p>
      )}
      {/* SEAM (T10): the "Share result" button goes here; it needs session.session_id. */}
      <div data-tid="play.result.share.seam" />
      <button type="button" onClick={onClose} data-tid="play.result.close"
        className="mt-4 min-h-[44px] rounded-lg bg-teal-700 px-5 py-2 text-sm font-semibold text-white">
        {closeLabel || t('result.back')}
      </button>
    </section>
  )
}
