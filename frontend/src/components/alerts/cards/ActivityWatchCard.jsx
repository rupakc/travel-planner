import { Star } from 'lucide-react'
import { Trans, useTranslation } from 'react-i18next'
import { fmtNumber } from '../../../i18n/format'
import { isUnavailable } from '../../../utils/priceWatch'
import {
  formatPrice, perPerson, providerName, titleDiffers, watchCurrency,
} from '../../../utils/activityWatch'
import PriceWatchCard from './PriceWatchCard'

function ActivityDetails({ watch }) {
  const { t } = useTranslation('alerts')
  const subject = watch.subject || {}
  const obs = watch.last_observation || {}
  const observed = obs.observed || {}
  const currency = watchCurrency(watch)
  const provider = providerName(subject.provider || observed.provider)
  const n = subject.travellers || 1
  const unit = perPerson(watch)
  const total = watch.last_price ?? watch.baseline_price
  const money = (v) => formatPrice(v, currency)
  const rating = observed.rating ?? null
  return (
    <div className="mt-3 space-y-1 text-sm text-slate-600">
      <p className="flex flex-wrap items-center gap-x-2 gap-y-0.5 text-xs text-slate-500">
        <span className="font-semibold uppercase tracking-wide">{provider}</span>
        {rating != null && (
          <span className="inline-flex items-center gap-0.5">
            <Star size={11} className="fill-amber-400 text-amber-400" aria-hidden="true" />{rating}
            {observed.reviews ? ` (${fmtNumber(observed.reviews)})` : ''}
          </span>
        )}
        {titleDiffers(subject.name, watch.title) && <span>{t('act.forName', { name: subject.name })}</span>}
      </p>
      {!isUnavailable(watch) && unit != null && (
        <p className="tabular-nums">
          {n > 1 && total != null
            ? (
              <Trans t={t} i18nKey="act.fromPersonTotal"
                values={{ unit: money(unit), people: t('act.people', { count: n }), total: money(total) }}
                components={{ strong: <strong className="text-slate-800" /> }} />
            )
            : (
              <Trans t={t} i18nKey="act.fromPerson" values={{ unit: money(unit) }}
                components={{ strong: <strong className="text-slate-800" /> }} />
            )}
        </p>
      )}
      {isUnavailable(watch) && observed.reason === 'currency_changed' && (
        <p className="text-xs text-slate-500">
          {t('act.currencyChanged', { seen: observed.seen_currency, currency })}
        </p>
      )}
      <p className="text-[11px] text-slate-400">{t('act.cardSource', { provider })}</p>
    </div>
  )
}

/** An activity price watch on the Alerts page (see ./PriceWatchCard). */
export default function ActivityWatchCard(props) {
  const { t } = useTranslation('alerts')
  return (
    <PriceWatchCard {...props} Details={ActivityDetails} openLabel={t('card.openListing')} unitLabel={t('unit.person')}
      unavailableText={t('act.unavailable')} />
  )
}
