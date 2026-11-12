import { useEffect, useRef } from 'react'
import { useTranslation } from 'react-i18next'
import { Check, Circle } from 'lucide-react'
import { useJourney } from '../../hooks/useJourney'
import { emit } from '../../telemetry/client'
import { planCompleteness } from '../../utils/planCompleteness'
import { fmtNumber } from '../../i18n/format'

const R = 20
const C = 2 * Math.PI * R

export default function CompletenessMeter({ selections, searchData, visaChecked = false, surface = 'drawer' }) {
  const { t } = useTranslation('completeness')
  const { enabled } = useJourney()
  const { percent, parts } = planCompleteness(selections, searchData, { visaChecked })
  const sent = useRef(false)

  useEffect(() => {
    if (!enabled || sent.current) return
    sent.current = true
    emit('completeness_view', { surface: surface === 'trip' ? 'trip' : 'drawer', percent })
  }, [enabled, surface, percent])

  if (!enabled) return null
  return (
    <section data-tid="completeness.meter" aria-label={t('title')}
      className="flex items-start gap-3 rounded-xl border border-gray-200 bg-white p-3">
      <div className="relative shrink-0 w-14 h-14" data-tid="completeness.ring">
        <svg viewBox="0 0 48 48" className="w-14 h-14 -rotate-90" role="img" aria-label={t('percent', { value: fmtNumber(percent) })}>
          <circle cx="24" cy="24" r={R} fill="none" strokeWidth="5" className="stroke-gray-200" />
          <circle cx="24" cy="24" r={R} fill="none" strokeWidth="5" strokeLinecap="round"
            className="stroke-teal-700" strokeDasharray={C} strokeDashoffset={C * (1 - percent / 100)} />
        </svg>
        <span className="absolute inset-0 flex items-center justify-center text-xs font-semibold text-gray-900">
          {t('percent', { value: fmtNumber(percent) })}
        </span>
      </div>
      <div className="min-w-0">
        <h3 className="text-sm font-semibold text-gray-900">{t('title')}</h3>
        <ul className="mt-1 space-y-0.5">
          {parts.map((p) => (
            <li key={p.id} data-tid={`completeness.part.${p.id}`} data-done={p.done ? 'true' : 'false'}
              className={`flex items-center gap-1.5 text-xs ${p.done ? 'text-gray-900' : 'text-gray-600'}`}>
              {p.done ? <Check size={12} className="text-teal-700" aria-hidden="true" /> : <Circle size={12} aria-hidden="true" />}
              <span>{t(`parts.${p.id}`)}</span>
              {!p.done && p.fraction > 0 && <span className="text-gray-500">{fmtNumber(Math.round(p.fraction * 100))}%</span>}
            </li>
          ))}
        </ul>
      </div>
    </section>
  )
}
