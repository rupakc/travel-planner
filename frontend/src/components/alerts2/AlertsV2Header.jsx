import { useEffect, useRef, useState } from 'react'
import { useLocation } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { PauseCircle, Settings2, X } from 'lucide-react'
import { useAlertsV2 } from '../../hooks/useAlertsV2'
import { emit } from '../../telemetry/client'
import { SORTS } from '../../utils/watchSort'
import SavingsTally from './SavingsTally'
import DealHunterTrack from './DealHunterTrack'
import AlertPrefsPanel from './AlertPrefsPanel'

const CHIP = 'inline-flex min-h-[44px] shrink-0 items-center rounded-full border px-4 text-sm font-medium focus-visible:outline focus-visible:outline-2 focus-visible:outline-teal-700'

/**
 * Top of the Alerts page in v2: the compact savings tally, the Deal-hunter
 * track, a calm banner while live checks are off, the preferences panel, the
 * sort chips and (for `?from=digest`) the weekly-digest entry.
 * `sort` / `onSort` are controlled by the page; alone it keeps its own.
 */
export default function AlertsV2Header({ sort: given, onSort }) {
  const { t } = useTranslation('alertsHub')
  const { livePrices } = useAlertsV2()
  const location = useLocation()
  const [own, setOwn] = useState('moving')
  const [prefsOpen, setPrefsOpen] = useState(false)
  const [digestShown, setDigestShown] = useState(true)
  const sort = given || own
  const params = new URLSearchParams(location.search)
  const fromDigest = params.get('from') === 'digest'
  const via = params.get('via') === 'in_app' ? 'in_app' : 'email_link'
  const sent = useRef(false)

  useEffect(() => {
    if (fromDigest && !sent.current) { sent.current = true; emit('alert_digest_open', { via }) }
  }, [fromDigest, via])

  const pick = (s) => { setOwn(s); if (onSort) onSort(s) }

  return (
    <section aria-label={t('title')} data-testid="alerts-v2-header" className="mb-6 space-y-4">
      {fromDigest && digestShown && (
        <div role="region" aria-label={t('digest.title')} data-testid="digest-entry"
          className="rounded-xl border border-teal-200 bg-teal-50 p-4 text-sm text-slate-800 dark:border-teal-800 dark:bg-teal-950/40 dark:text-slate-100">
          <div className="flex items-start justify-between gap-3">
            <div>
              <h2 className="font-semibold">{t('digest.title')}</h2>
              <p className="mt-1 text-slate-600 dark:text-slate-300">{t('digest.body')}</p>
            </div>
            <button type="button" data-tid="alerts.digest-dismiss" aria-label={t('digest.dismiss')} onClick={() => setDigestShown(false)}
              className="inline-flex min-h-[44px] min-w-[44px] items-center justify-center rounded-lg hover:bg-teal-100 dark:hover:bg-teal-900">
              <X className="h-4 w-4" aria-hidden="true" />
            </button>
          </div>
        </div>
      )}

      {!livePrices && (
        <div role="status" data-testid="live-paused" data-tid="alerts.live-paused"
          className="flex items-start gap-3 rounded-xl border border-slate-200 bg-slate-50 p-4 text-sm text-slate-700 dark:border-slate-700 dark:bg-slate-800/60 dark:text-slate-200">
          <PauseCircle className="mt-0.5 h-5 w-5 shrink-0 text-slate-500" aria-hidden="true" />
          <div>
            <p className="font-semibold">{t('paused.title')}</p>
            <p className="mt-0.5 text-slate-600 dark:text-slate-300">{t('paused.body')}</p>
          </div>
        </div>
      )}

      <div className="space-y-3 rounded-xl border border-slate-200 p-4 dark:border-slate-700">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <SavingsTally compact />
          <button type="button" data-tid="alerts.prefs-toggle" aria-expanded={prefsOpen} aria-controls="alerts-prefs-panel"
            onClick={() => setPrefsOpen((o) => !o)}
            className="inline-flex min-h-[44px] items-center gap-2 rounded-lg border border-slate-300 px-4 text-sm font-medium text-slate-800 hover:bg-slate-50 dark:border-slate-600 dark:text-slate-100 dark:hover:bg-slate-800">
            <Settings2 className="h-4 w-4" aria-hidden="true" />{t('prefs.button')}
          </button>
        </div>
        <DealHunterTrack />
      </div>

      {prefsOpen && (
        <div id="alerts-prefs-panel" role="region" aria-label={t('prefs.button')} data-testid="prefs-region"
          className="rounded-xl border border-slate-200 p-4 dark:border-slate-700">
          <AlertPrefsPanel />
        </div>
      )}

      <div role="group" aria-label={t('sort.label')} className="-mx-1 flex gap-2 overflow-x-auto px-1">
        {SORTS.map((s) => (
          <button key={s} type="button" data-tid={`alerts.sort-${s}`} aria-pressed={sort === s} onClick={() => pick(s)}
            className={`${CHIP} ${sort === s ? 'border-teal-700 bg-teal-700 text-white' : 'border-slate-300 bg-white text-slate-700 hover:border-slate-400 dark:border-slate-600 dark:bg-slate-900 dark:text-slate-200'}`}>
            {t(`sort.${s}`)}
          </button>
        ))}
      </div>
    </section>
  )
}
