import { useTranslation } from 'react-i18next'
import { fmtNumber } from '../i18n/format'

const CLASSES = ['economy', 'premiumEconomy', 'business', 'first']

/** "≈ N kg CO₂e" for one flight result, from Google's Travel Impact Model.
 * Renders nothing when the backend sent no usable `emissions` (older backend,
 * feature off, or a flight TIM can't estimate). The chip links to TIM (the
 * CC BY-SA attribution); its tooltip gives the per-class breakdown. */
export default function EmissionsChip({ emissions }) {
  const { t } = useTranslation('results')
  const kg = emissions?.kg_co2e_per_pax
  if (typeof kg !== 'number' || !Number.isFinite(kg)) return null
  const byClass = emissions.by_class || {}
  const lines = CLASSES
    .filter(c => typeof byClass[c] === 'number')
    .map(c => t('emissions.classLine', { cls: t(`emissions.class.${c}`), kg: fmtNumber(byClass[c]) }))
  const tooltip = [t('emissions.perPassenger'), ...lines, t('emissions.attribution')].join('\n')
  const href = emissions.attribution_url || 'https://travelimpactmodel.org'
  return (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      title={tooltip}
      aria-label={`${t('emissions.chip', { kg: fmtNumber(kg) })}. ${tooltip}`}
      onClick={e => e.stopPropagation()}
      data-tid="results.flight.emissions"
      className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-emerald-50 text-emerald-700 border border-emerald-200 hover:bg-emerald-100"
    >
      {t('emissions.chip', { kg: fmtNumber(kg) })}
    </a>
  )
}
