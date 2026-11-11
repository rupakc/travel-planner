import { ExternalLink, Star } from 'lucide-react'
import { Trans, useTranslation } from 'react-i18next'
import { fmtNumber } from '../../../i18n/format'
import {
  formatPrice, perPerson, providerName, titleDiffers, watchCurrency,
} from '../../../utils/activityWatch'

import { formatDay } from '../../../utils/fareCalendar'

function dayLabel(iso) {
  const d = new Date(`${iso}T12:00:00`)
  return Number.isNaN(d.getTime()) ? iso : formatDay(iso)
}

/**
 * Activity body of the price-watch dialog. Before matching: what we'll look
 * for and the AI estimate, labelled. Once watched: the matched GetYourGuide /
 * Viator listing (provider as text), its rating, "from $X per person" ×
 * travellers, a link to it and where the price comes from. Money is always
 * in the watch's own currency once there is a watch (a picked suggestion may
 * differ from what the page showed).
 */
export default function ActivityDialogBody({ spec = {}, watch = null }) {
  const { t } = useTranslation('alerts')
  if (watch) return <Matched watch={watch} />
  const n = spec.travellers || 1
  const people = t('act.people', { count: n })
  if (spec.listing_url) {
    return (
      <div className="mt-3 rounded-xl bg-slate-50 px-4 py-3 text-sm text-slate-600">
        <p>
          <Trans t={t} i18nKey={n > 1 ? 'act.watchListingPeople' : 'act.watchListing'}
            values={{ name: spec.name, people }}
            components={{ strong: <strong className="text-slate-800" /> }} />
        </p>
        <a href={spec.listing_url} data-tid="alerts.activity-listing" target="_blank" rel="noopener noreferrer"
          className="mt-1 inline-flex items-center gap-1 text-xs font-medium text-sky-700 underline-offset-2 hover:underline">
          <ExternalLink size={11} aria-hidden="true" /> {t('act.seeListing')}
        </a>
      </div>
    )
  }
  return (
    <div className="mt-3 rounded-xl bg-slate-50 px-4 py-3 text-sm text-slate-600">
      <p>
        <Trans t={t} i18nKey={`act.lookFor${spec.city ? 'City' : ''}${n > 1 ? 'People' : ''}`}
          values={{ name: spec.name, city: spec.city, people }}
          components={{ strong: <strong className="text-slate-800" /> }} />
      </p>
      {spec.date && <p className="mt-1 text-xs text-slate-500">{t('act.forDay', { day: dayLabel(spec.date) })}</p>}
      {spec.estimate_price != null && (
        <p className="mt-1.5 text-xs text-slate-500">
          {t('act.estimate', { price: formatPrice(spec.estimate_price, 'USD') })}
        </p>
      )}
    </div>
  )
}

function Matched({ watch }) {
  const { t } = useTranslation('alerts')
  const subject = watch.subject || {}
  const obs = watch.last_observation || {}
  const observed = obs.observed || {}
  const currency = watchCurrency(watch)
  const provider = providerName(subject.provider || observed.provider)
  const title = subject.listing_title || watch.title
  const link = watch.link || obs.link || subject.listing_url
  const n = subject.travellers || 1
  const unit = perPerson(watch)
  const total = watch.last_price ?? watch.baseline_price
  const money = (v) => formatPrice(v, currency)
  return (
    <div className="rounded-xl border border-emerald-100 bg-white px-3 py-2.5 text-slate-700">
      <p className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">{provider}</p>
      <p className="text-sm font-semibold text-slate-900">{title}</p>
      {observed.rating != null && (
        <p className="mt-0.5 flex items-center gap-1 text-xs text-slate-500">
          <Star size={11} className="fill-amber-400 text-amber-400" aria-hidden="true" />
          <span>{observed.reviews ? t('act.reviews', { count: observed.reviews, rating: observed.rating, formatted: fmtNumber(observed.reviews) }) : observed.rating}</span>
        </p>
      )}
      {unit != null && (
        <p className="mt-1.5 text-sm tabular-nums">
          {n > 1 && total != null
            ? <Trans t={t} i18nKey="act.fromPersonTotal" values={{ unit: money(unit), people: t('act.people', { count: n }), total: money(total) }} components={{ strong: <strong /> }} />
            : <Trans t={t} i18nKey="act.fromPerson" values={{ unit: money(unit) }} components={{ strong: <strong /> }} />}
        </p>
      )}
      {titleDiffers(subject.name, title) && (
        <p className="mt-1.5 text-xs text-amber-800">
          {t('act.closest', { name: subject.name })}
        </p>
      )}
      <p className="mt-1.5 text-[11px] text-slate-500">
        {t('act.priceSource', { provider })}
        {currency !== 'USD' && ` ${t('act.currencyNote', { currency })}`}
      </p>
      {link && (
        <a href={link} data-tid="alerts.activity-provider" target="_blank" rel="noopener noreferrer"
          className="mt-1.5 inline-flex items-center gap-1 text-xs font-medium text-sky-700 underline-offset-2 hover:underline">
          <ExternalLink size={11} aria-hidden="true" /> {t('act.seeOn', { provider })}
        </a>
      )}
    </div>
  )
}
