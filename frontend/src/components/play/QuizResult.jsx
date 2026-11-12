import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Share2 } from 'lucide-react'
import { useClientConfig } from '../../hooks/useClientConfig'
import { sharingEnabled } from '../../utils/share'
import ShareDialog from '../share/ShareDialog'
import { xpEarned } from './quizText'

// Result of a finished quiz: score, XP, streak and (when the backend can) a share link.
export default function QuizResult({ summary, sessionId, onClose, closeLabel }) {
  const { t } = useTranslation('play')
  const { t: ts } = useTranslation('share')
  const { config } = useClientConfig()
  const [sharing, setSharing] = useState(false)
  const canShare = !!sessionId && sharingEnabled(config) && Number(config?.features?.play) >= 1
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
      {canShare && (
        <div>
          <button type="button" onClick={() => setSharing(true)} data-tid="play.result.share"
            className="mt-3 inline-flex min-h-[44px] items-center justify-center gap-2 rounded-lg border border-slate-300 px-4 text-sm font-medium text-slate-800">
            <Share2 size={16} aria-hidden="true" />{ts('quizCta')}
          </button>
        </div>
      )}
      {canShare && sharing && <ShareDialog kind="quiz" sessionId={sessionId} onClose={() => setSharing(false)} />}
      <button type="button" onClick={onClose} data-tid="play.result.close"
        className="mt-4 min-h-[44px] rounded-lg bg-teal-700 px-5 py-2 text-sm font-semibold text-white">
        {closeLabel || t('result.back')}
      </button>
    </section>
  )
}
