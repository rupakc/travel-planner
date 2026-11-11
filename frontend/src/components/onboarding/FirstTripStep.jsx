import { useTranslation } from 'react-i18next'
import { Loader2, Plane, Compass } from 'lucide-react'
import { primaryBtn, secondaryBtn } from './QuizStep'

/**
 * Step 5: plan a first trip (→ /explore) or just explore (→ /). Either one
 * finishes onboarding; a preferences sync failure offers Retry or
 * "Continue without syncing".
 */
export default function FirstTripStep({ saving, syncError, onBack, onFinish, onRetry, onContinueUnsynced }) {
  const { t } = useTranslation('onboarding')
  return (
    <section data-tid="onboarding.step.first-trip" aria-labelledby="onboarding-trip-title" className="space-y-5">
      <div>
        <h2 id="onboarding-trip-title" className="font-display text-xl sm:text-2xl font-semibold text-gray-900">
          {t('steps.firstTrip.title')}
        </h2>
        <p className="text-sm text-gray-600 mt-1">{t('steps.firstTrip.body')}</p>
      </div>

      {syncError ? (
        <div data-tid="onboarding.sync-error" role="alert" className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 space-y-3">
          <div>
            <p className="text-sm font-semibold text-red-800">{t('web.syncFailed')}</p>
            {syncError.detail && <p className="text-xs text-red-800 mt-0.5">{syncError.detail}</p>}
            <p className="text-xs text-red-800 mt-1">{t('web.syncFailedBody')}</p>
          </div>
          <div className="flex flex-wrap gap-2">
            <button type="button" data-tid="onboarding.retry" onClick={onRetry} disabled={saving} className={primaryBtn}>
              {saving ? t('web.saving') : t('web.retry')}
            </button>
            <button type="button" data-tid="onboarding.continue-unsynced" onClick={onContinueUnsynced} disabled={saving} className={secondaryBtn}>
              {t('web.continueWithoutSync')}
            </button>
          </div>
        </div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <button
            type="button"
            data-tid="onboarding.first-trip"
            onClick={() => onFinish('/explore')}
            disabled={saving}
            className="min-h-[88px] flex flex-col items-start gap-2 text-left px-4 py-4 rounded-2xl bg-teal-700 hover:bg-teal-800 text-white disabled:opacity-60"
          >
            <Plane size={22} aria-hidden="true" />
            <span className="text-sm font-semibold">{t('web.firstTrip')}</span>
          </button>
          <button
            type="button"
            data-tid="onboarding.explore"
            onClick={() => onFinish('/')}
            disabled={saving}
            className="min-h-[88px] flex flex-col items-start gap-2 text-left px-4 py-4 rounded-2xl border border-gray-200 bg-white text-gray-900 hover:border-gray-300 disabled:opacity-60"
          >
            <Compass size={22} aria-hidden="true" className="text-teal-700" />
            <span className="text-sm font-semibold">{t('web.explore')}</span>
          </button>
        </div>
      )}

      {saving && !syncError && (
        <p data-tid="onboarding.saving" role="status" className="flex items-center gap-2 text-sm text-gray-600">
          <Loader2 size={16} className="motion-safe:animate-spin" aria-hidden="true" /> {t('web.saving')}
        </p>
      )}

      <div className="pt-1">
        <button type="button" data-tid="onboarding.back" onClick={onBack} disabled={saving} className={secondaryBtn}>{t('nav.back')}</button>
      </div>
    </section>
  )
}
