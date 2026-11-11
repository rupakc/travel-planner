import { useTranslation } from 'react-i18next'
import { passwordStrength } from '../../utils/passwordStrength'

const BAR = ['bg-red-500', 'bg-orange-500', 'bg-amber-500', 'bg-lime-500', 'bg-emerald-500']

// Four-segment meter + the first couple of improvement hints. Advice only; the
// server decides what is accepted. Renders nothing until something is typed.
export default function PasswordStrengthMeter({ password, username, email }) {
  const { t } = useTranslation('signup')
  if (!password) return null
  const { score, hints } = passwordStrength(password, { username, email })
  return (
    <div data-tid="signup.strength" data-score={score} className="mt-2" aria-live="polite">
      <div className="flex gap-1" aria-hidden="true">
        {[0, 1, 2, 3].map((i) => (
          <span key={i}
            className={`h-1.5 flex-1 rounded-full ${i < Math.max(score, 1) ? BAR[score] : 'bg-gray-200'}`} />
        ))}
      </div>
      <p className="mt-1 text-xs text-gray-600">
        {t('strength.label', { level: t(`strength.level.${score}`) })}
        {hints.slice(0, 2).map((h) => ` · ${t(`strength.hint.${h}`)}`)}
      </p>
    </div>
  )
}
