import { useTranslation } from 'react-i18next'
import { Compass } from 'lucide-react'
import { classify, nothingScored } from '../../utils/travellerQuiz'
import { primaryBtn, secondaryBtn } from './QuizStep'

/** The quiz result: primary type, "Also a bit of" secondaries, Change answers / Continue. */
export default function TravellerTypeResult({ answers, onChangeAnswers, onContinue }) {
  const { t } = useTranslation('onboarding')
  const { primary, secondary } = classify(answers)
  const skipped = nothingScored(answers)

  return (
    <section data-tid="onboarding.result" aria-live="polite" className="space-y-5">
      <div className="flex items-start gap-4">
        <span aria-hidden="true" className="shrink-0 w-12 h-12 rounded-2xl bg-teal-100 text-teal-800 flex items-center justify-center">
          <Compass size={26} />
        </span>
        <div>
          <p className="text-sm font-medium text-gray-600">{t('web.resultHeading')}</p>
          <h2 data-tid="onboarding.result.primary" className="font-display text-2xl font-semibold text-gray-900">
            {t(`types.${primary}.name`)}
          </h2>
          <p className="text-sm text-gray-700 mt-1">{t(`types.${primary}.description`)}</p>
        </div>
      </div>
      {secondary.length > 0 && (
        <div data-tid="onboarding.result.secondary">
          <p className="text-sm font-medium text-gray-600 mb-2">{t('web.resultAlso')}</p>
          <ul className="space-y-2">
            {secondary.map((type) => (
              <li key={type} className="rounded-xl border border-gray-200 bg-white px-4 py-3">
                <p className="text-sm font-semibold text-gray-900">{t(`types.${type}.name`)}</p>
                <p className="text-xs text-gray-600">{t(`types.${type}.description`)}</p>
              </li>
            ))}
          </ul>
        </div>
      )}
      {skipped && <p data-tid="onboarding.result.skipped" className="text-sm text-gray-600">{t('web.resultSkipped')}</p>}
      <div className="flex flex-col-reverse sm:flex-row sm:items-center sm:justify-between gap-2 pt-1">
        <button type="button" data-tid="onboarding.change-answers" onClick={onChangeAnswers} className={secondaryBtn}>
          {t('web.changeAnswers')}
        </button>
        <button type="button" data-tid="onboarding.next" onClick={onContinue} className={primaryBtn}>
          {t('web.continue')}
        </button>
      </div>
    </section>
  )
}
