import { useTranslation } from 'react-i18next'
import { fmtNumber } from '../i18n/format'
import { Package, Plane, Hotel, MapPin, Smartphone, Footprints, Landmark, Check, Undo2 } from 'lucide-react'
import { safeUrl } from '../utils/planPrint'
import { computePlanCost } from '../utils/planHelpers'
import { isPackageApplied, packageConflicts } from '../utils/bestValuePackage'

const usd = (n) => fmtNumber(Number(n), { style: 'currency', currency: 'USD', maximumFractionDigits: 0 })

const ICONS = {
  flight: Plane,
  flights: Plane,
  hotel: Hotel,
  activities: MapPin,
  walking_tours: Footprints,
  places_to_see: Landmark,
  sim: Smartphone,
}

const known = (n) => n != null && n !== '' && Number.isFinite(Number(n))

function describe({ type, item }, t) {
  const it = item || {}
  switch (type) {
    case 'flight':
    case 'flights': {
      const airline = it.outbound?.airline ?? it.airline
      const number = it.outbound?.flight_number ?? it.flight_number
      return {
        name: [airline, number].filter(Boolean).join(' ') || t('best.flight'),
        href: it.booking_url,
        price: known(it.price_usd) ? usd(it.price_usd) : null,
      }
    }
    case 'hotel':
      return {
        name: it.name,
        href: it.booking_url,
        price: known(it.price_per_night_usd) ? t('best.perNight', { price: usd(it.price_per_night_usd) }) : null,
      }
    case 'activities':
      return {
        name: it.name,
        href: it.booking_url,
        price: known(it.price_usd) ? (Number(it.price_usd) === 0 ? t('best.free') : usd(it.price_usd)) : null,
      }
    case 'walking_tours':
      return { name: it.name, href: it.url, price: null }
    case 'places_to_see':
      return { name: it.name, href: it.info_url, price: null }
    case 'sim':
      return {
        name: [it.provider, it.plan_name].filter(Boolean).join(' ') || t('best.simPlan'),
        href: it.url,
        price: known(it.price_usd) ? usd(it.price_usd) : null,
      }
    default:
      return { name: it.name || '', href: null, price: null }
  }
}

const joinLabels = (labels, t) =>
  labels.length < 2
    ? labels.join('')
    : t('best.listAnd', { head: labels.slice(0, -1).join(t('best.listSep')), last: labels[labels.length - 1] })

function Row({ entry }) {
  const { t } = useTranslation('plan')
  const Icon = ICONS[entry.type] || MapPin
  const { name, href, price } = describe(entry, t)
  const safe = href ? safeUrl(href) : null
  const label = safe ? (
    <a
      href={safe}
      data-tid="plan.best-item-link"
      target="_blank"
      rel="noopener noreferrer"
      className="text-sm font-semibold text-gray-800 hover:text-teal-700 hover:underline break-words focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-500 rounded"
    >
      {name}
    </a>
  ) : (
    <span className="text-sm font-semibold text-gray-800 break-words">{name}</span>
  )
  return (
    <li className="flex items-start gap-3 py-2">
      <div className="w-7 h-7 shrink-0 rounded-lg bg-teal-50 flex items-center justify-center">
        <Icon size={14} className="text-teal-600" />
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5">
          {label}
          {entry.city && (
            <span className="text-[10px] font-semibold px-1.5 py-0.5 rounded-full bg-gray-100 text-gray-600">{entry.city}</span>
          )}
          {price && <span className="text-xs font-semibold text-teal-700">{price}</span>}
        </div>
        <p className="text-xs text-gray-500">{entry.reason}</p>
      </div>
    </li>
  )
}

export default function BestValuePackage({ pkg, selections, searchData, onApply, onUndo, canUndo, disabledReason }) {
  const { t } = useTranslation('plan')
  if (!pkg) return null
  const applied = isPackageApplied(selections, pkg)
  const conflicts = applied ? [] : packageConflicts(selections, pkg)
  const hasFlight = pkg.items.some((i) => i.type === 'flight' || i.type === 'flights')
  const disabled = applied || !!disabledReason
  const planTotal = applied ? computePlanCost(selections, searchData) : null
  const showPlanTotal = planTotal !== null && Math.round(planTotal) !== Math.round(pkg.total)
  const over = pkg.budget?.status === 'over'

  return (
    <div className="bg-white rounded-xl shadow-md border border-gray-100 ring-1 ring-black/5 p-4">
      <div className="flex items-center gap-2 mb-2">
        <div className="w-7 h-7 shrink-0 rounded-lg bg-gradient-to-br from-teal-500 to-emerald-500 flex items-center justify-center">
          <Package size={14} className="text-white" />
        </div>
        <div>
          <h3 className="text-sm font-bold text-gray-800">{t('best.title')}</h3>
          <p className="text-xs text-gray-500">{t('best.subtitle')}</p>
        </div>
      </div>

      <ul className="divide-y divide-gray-100">
        {pkg.items.map((entry, i) => (
          <Row key={`${entry.type}-${i}`} entry={entry} />
        ))}
      </ul>

      <div className="mt-3 flex flex-wrap items-center gap-x-2 gap-y-1">
        <span className="text-xs text-gray-500">{t('best.total')}</span>
        <span className="text-base font-bold text-gray-900">{usd(pkg.total)}</span>
        {pkg.budget && (
          <span
            className={`text-xs font-semibold px-2 py-0.5 rounded-full border ${
              over ? 'bg-red-50 text-red-700 border-red-200' : 'bg-emerald-50 text-emerald-700 border-emerald-200'
            }`}
          >
            {pkg.budget.label}
          </span>
        )}
      </div>
      {showPlanTotal && <p className="text-xs text-gray-600 mt-1">{t('best.myPlanTotal', { amount: usd(planTotal) })}</p>}
      {hasFlight && <p className="text-xs text-gray-500 mt-1">{t('best.perPerson')}</p>}

      <div className="mt-3 flex flex-wrap items-center gap-2">
        <button
          type="button"
          onClick={onApply}
          data-tid="plan.best-apply"
          disabled={disabled}
          className={`flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-semibold border transition-all focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-500 focus-visible:ring-offset-1 ${
            disabled
              ? 'bg-gray-50 text-gray-400 border-gray-200 cursor-not-allowed'
              : 'bg-teal-700 text-white border-teal-600 hover:bg-teal-800'
          }`}
        >
          {applied && <Check size={12} />}
          {applied ? t('best.added') : t('best.add')}
        </button>
        {applied && canUndo && (
          <button
            type="button"
            onClick={onUndo}
            data-tid="plan.best-undo"
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-semibold border bg-white text-gray-700 border-gray-200 hover:bg-gray-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-500 focus-visible:ring-offset-1"
          >
            <Undo2 size={12} />{t('best.undo')}
          </button>
        )}
      </div>
      <div aria-live="polite" className="text-xs mt-1.5">
        {disabledReason ? (
          <p className="text-amber-700">{disabledReason}</p>
        ) : conflicts.length > 0 ? (
          <p className="text-gray-500">{t('best.replaces', { items: joinLabels(conflicts.map((c) => t(`best.conflict.${c.toLowerCase()}`)), t) })}</p>
        ) : applied ? (
          <p className="text-emerald-700">{t('best.added')}</p>
        ) : null}
      </div>
    </div>
  )
}
