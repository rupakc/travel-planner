import { useState } from 'react'
import { Link2, X, Loader2, CheckCircle2, AlertTriangle } from 'lucide-react'
import { Trans, useTranslation } from 'react-i18next'
import { linkCoverageSummary } from '../utils/linkImport'
import { safeUrl } from '../utils/planPrint'

/** Results banner for a trip imported from a link: how many of its places
 *  made it into the itinerary. */
export default function LinkPlanBanner({ searchData, itinerary, failed = false }) {
  const { t } = useTranslation('misc')
  const [dismissed, setDismissed] = useState(false)
  const [showMissing, setShowMissing] = useState(false)
  const summary = linkCoverageSummary(searchData, itinerary, { failed })
  if (!summary || dismissed) return null
  const href = safeUrl(searchData.import_source?.url)
  const title = summary.title || t('linkPlan.yourLink')
  const source = href
    ? <a href={href} data-tid="link-plan.source" target="_blank" rel="noopener noreferrer nofollow ugc" className="font-semibold italic underline decoration-amber-400 decoration-2 underline-offset-2 hover:decoration-amber-600">{title}</a>
    : <span className="font-semibold italic">{title}</span>
  const n = summary.total
  const pending = summary.state === 'pending'
  const broken = summary.state === 'failed'
  const all = summary.state === 'ready' && summary.inItinerary === n

  return (
    <div role="status" className="flex items-start gap-3 rounded-2xl bg-gradient-to-r from-amber-50 to-orange-50/70 p-3.5 ring-1 ring-amber-200 sm:p-4">
      <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-amber-400 text-amber-950">
        {pending ? <Loader2 size={17} className="animate-spin" /> : broken ? <AlertTriangle size={17} /> : all ? <CheckCircle2 size={18} /> : <Link2 size={17} />}
      </span>
      <div className="min-w-0 flex-1 text-sm text-gray-800">
        <p>
          {pending
            ? <Trans t={t} i18nKey="linkPlan.fitting" count={n} components={{ src: source }} />
            : broken
            ? <Trans t={t} i18nKey="linkPlan.failed" count={n} components={{ src: source }} />
            : all
            ? <Trans t={t} i18nKey="linkPlan.all" count={n} components={{ src: source }} />
            : <>
                <Trans t={t} i18nKey="linkPlan.some" count={n} values={{ inItinerary: summary.inItinerary }} components={{ src: source }} />{' '}
                <button type="button" onClick={() => setShowMissing((v) => !v)} aria-expanded={showMissing}
                  data-tid="link-plan.toggle-missing"
                  className="font-medium text-amber-800 underline underline-offset-2 hover:text-amber-950">
                  {t(showMissing ? 'linkPlan.didntFit' : 'linkPlan.didntFitShow', { n: summary.missing.length })}
                </button></>}
        </p>
        {showMissing && summary.missing.length > 0 && (
          <p data-missing className="mt-1 text-xs text-gray-600">
            {t('linkPlan.missing', { names: summary.missing.join(', ') })}
          </p>
        )}
        {summary.state === 'ready' && <p className="mt-0.5 text-xs text-amber-900/70">{t('linkPlan.hint', { tag: t('fromLink.chip') })}</p>}
      </div>
      <button type="button" data-tid="link-plan.dismiss" aria-label={t('linkPlan.dismiss')} onClick={() => setDismissed(true)}
        className="shrink-0 rounded-full p-1 text-amber-800/60 hover:bg-amber-100 hover:text-amber-900">
        <X size={15} />
      </button>
    </div>
  )
}
