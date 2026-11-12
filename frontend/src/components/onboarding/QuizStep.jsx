import { useTranslation } from 'react-i18next'
import { Check } from 'lucide-react'
import OnboardingProgress from './OnboardingProgress'
import { QUESTIONS } from '../../utils/travellerQuiz'

export const primaryBtn =
  'min-h-[44px] px-5 rounded-xl bg-teal-700 hover:bg-teal-800 text-white text-sm font-semibold disabled:opacity-50 disabled:cursor-not-allowed'
export const secondaryBtn =
  'min-h-[44px] px-4 rounded-xl text-sm font-medium text-gray-700 hover:bg-gray-100'

/** One quiz question: radio cards (single choice) or checkbox cards (multi). */
export default function QuizStep({ index, selected, onToggle, onBack, onSkip, onNext }) {
  const { t } = useTranslation('onboarding')
  const question = QUESTIONS[index]
  const multi = question.multiChoice
  const last = index === QUESTIONS.length - 1
  const titleId = `onboarding-q-${question.id}`

  return (
    <section data-tid="onboarding.step.quiz" aria-labelledby={titleId} className="space-y-5">
      <OnboardingProgress
        tid="onboarding.quiz.progress"
        current={index + 1}
        count={QUESTIONS.length}
        label={t('web.questionOf', { n: index + 1, count: QUESTIONS.length })}
      />
      <div>
        <h2 id={titleId} className="font-display text-xl sm:text-2xl font-semibold text-gray-900">
          {t(`quiz.${question.id}.title`)}
        </h2>
        <p className="text-sm text-gray-600 mt-1">{multi ? t('web.chooseMany') : t('web.chooseOne')}</p>
      </div>
      <div
        role={multi ? 'group' : 'radiogroup'}
        aria-labelledby={titleId}
        className="grid grid-cols-1 sm:grid-cols-2 gap-2"
      >
        {question.options.map((option) => {
          const on = selected.includes(option.id)
          return (
            <button
              key={option.id}
              type="button"
              role={multi ? 'checkbox' : 'radio'}
              aria-checked={on}
              data-tid={`onboarding.option.${question.id}.${option.id}`}
              onClick={() => onToggle(option.id)}
              className={`min-h-[48px] flex items-center justify-between gap-3 text-left px-4 py-3 rounded-xl border text-sm font-medium motion-safe:transition-colors ${
                on
                  ? 'border-teal-700 bg-teal-50 text-teal-900 ring-1 ring-teal-700'
                  : 'border-gray-200 bg-white text-gray-800 hover:border-gray-300'
              }`}
            >
              <span>{t(`quiz.${question.id}.options.${option.id}`)}</span>
              <span
                aria-hidden="true"
                className={`shrink-0 w-5 h-5 flex items-center justify-center border ${multi ? 'rounded' : 'rounded-full'} ${
                  on ? 'bg-teal-700 border-teal-700 text-white' : 'border-gray-300'
                }`}
              >
                {on && <Check size={14} strokeWidth={3} />}
              </span>
            </button>
          )
        })}
      </div>
      <div className="flex items-center justify-between gap-2 pt-1">
        <button type="button" data-tid="onboarding.quiz.back" onClick={onBack} className={secondaryBtn}>
          {t('nav.back')}
        </button>
        <div className="flex items-center gap-2">
          <button type="button" data-tid="onboarding.quiz.skip" onClick={onSkip} className={secondaryBtn}>
            {t('nav.skip')}
          </button>
          <button
            type="button"
            data-tid="onboarding.quiz.next"
            onClick={onNext}
            disabled={selected.length === 0}
            className={primaryBtn}
          >
            {last ? t('nav.seeType') : t('nav.next')}
          </button>
        </div>
      </div>
    </section>
  )
}
