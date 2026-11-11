import { useTranslation } from 'react-i18next'
import AirportSearch from '../ui/AirportSearch'
import NationalitySearch from '../ui/NationalitySearch'
import { primaryBtn, secondaryBtn } from './QuizStep'

/** Step 3: home airport (device-only) and passport (→ Preferences.nationality). */
export default function HomePassportStep({ airport, passport, onAirport, onPassport, onBack, onSkip, onNext }) {
  const { t } = useTranslation('onboarding')
  return (
    <section data-tid="onboarding.step.home" aria-labelledby="onboarding-home-title" className="space-y-5">
      <div>
        <h2 id="onboarding-home-title" className="font-display text-xl sm:text-2xl font-semibold text-gray-900">
          {t('steps.homeAndPassport.title')}
        </h2>
        <p className="text-sm text-gray-600 mt-1">{t('steps.homeAndPassport.body')}</p>
      </div>
      <div data-tid="onboarding.home-airport">
        <AirportSearch label={t('web.homeAirport')} value={airport} onChange={onAirport} placeholder={t('web.homeAirportPlaceholder')} />
        <p className="text-xs text-gray-600 mt-1">{t('web.homeAirportHint')}</p>
      </div>
      <div data-tid="onboarding.passport">
        <NationalitySearch label={t('web.passport')} value={passport} onChange={onPassport} placeholder={t('web.passportPlaceholder')} />
        <p className="text-xs text-gray-600 mt-1">{t('web.passportHint')}</p>
      </div>
      <div className="flex items-center justify-between gap-2 pt-1">
        <button type="button" data-tid="onboarding.back" onClick={onBack} className={secondaryBtn}>{t('nav.back')}</button>
        <div className="flex items-center gap-2">
          <button type="button" data-tid="onboarding.skip" onClick={onSkip} className={secondaryBtn}>{t('nav.skip')}</button>
          <button type="button" data-tid="onboarding.next" onClick={onNext} className={primaryBtn}>{t('nav.next')}</button>
        </div>
      </div>
    </section>
  )
}
