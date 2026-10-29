import { Package, Plane, Hotel, MapPin, Smartphone, Footprints, Landmark, Check, Undo2 } from 'lucide-react'
import { safeUrl } from '../utils/planPrint'
import { isPackageApplied, packageConflicts } from '../utils/bestValuePackage'

const usd = (n) => `$${Number(n).toLocaleString(undefined, { maximumFractionDigits: 0 })}`

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

function describe({ type, item }) {
  const it = item || {}
  switch (type) {
    case 'flight':
    case 'flights': {
      const airline = it.outbound?.airline ?? it.airline
      const number = it.outbound?.flight_number ?? it.flight_number
      return {
        name: [airline, number].filter(Boolean).join(' ') || 'Flight',
        href: it.booking_url,
        price: known(it.price_usd) ? usd(it.price_usd) : null,
      }
    }
    case 'hotel':
      return {
        name: it.name,
        href: it.booking_url,
        price: known(it.price_per_night_usd) ? `${usd(it.price_per_night_usd)}/night` : null,
      }
    case 'activities':
      return {
        name: it.name,
        href: it.booking_url,
        price: known(it.price_usd) ? (Number(it.price_usd) === 0 ? 'Free' : usd(it.price_usd)) : null,
      }
    case 'walking_tours':
      return { name: it.name, href: it.url, price: null }
    case 'places_to_see':
      return { name: it.name, href: it.info_url, price: null }
    case 'sim':
      return {
        name: [it.provider, it.plan_name].filter(Boolean).join(' ') || 'SIM plan',
        href: it.url,
        price: known(it.price_usd) ? usd(it.price_usd) : null,
      }
    default:
      return { name: it.name || '', href: null, price: null }
  }
}

const joinLabels = (labels) =>
  labels.length < 2 ? labels.join('') : `${labels.slice(0, -1).join(', ')} and ${labels[labels.length - 1]}`

function Row({ entry }) {
  const Icon = ICONS[entry.type] || MapPin
  const { name, href, price } = describe(entry)
  const safe = href ? safeUrl(href) : null
  const label = safe ? (
    <a
      href={safe}
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

export default function BestValuePackage({ pkg, selections, onApply, onUndo, canUndo, disabledReason }) {
  if (!pkg) return null
  const applied = isPackageApplied(selections, pkg)
  const conflicts = applied ? [] : packageConflicts(selections, pkg)
  const hasFlight = pkg.items.some((i) => i.type === 'flight' || i.type === 'flights')
  const disabled = applied || !!disabledReason
  const over = pkg.budget?.status === 'over'

  return (
    <div className="bg-white rounded-xl shadow-md border border-gray-100 ring-1 ring-black/5 p-4">
      <div className="flex items-center gap-2 mb-2">
        <div className="w-7 h-7 shrink-0 rounded-lg bg-gradient-to-br from-teal-500 to-emerald-500 flex items-center justify-center">
          <Package size={14} className="text-white" />
        </div>
        <div>
          <h3 className="text-sm font-bold text-gray-800">Best-value package</h3>
          <p className="text-xs text-gray-500">Our picks for the best price-to-quality balance from your results</p>
        </div>
      </div>

      <ul className="divide-y divide-gray-100">
        {pkg.items.map((entry, i) => (
          <Row key={`${entry.type}-${i}`} entry={entry} />
        ))}
      </ul>

      <div className="mt-3 flex flex-wrap items-center gap-x-2 gap-y-1">
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
      {hasFlight && <p className="text-xs text-gray-500 mt-1">Flight prices are per person</p>}

      <div className="mt-3 flex flex-wrap items-center gap-2">
        <button
          type="button"
          onClick={onApply}
          disabled={disabled}
          className={`flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-semibold border transition-all focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-500 focus-visible:ring-offset-1 ${
            disabled
              ? 'bg-gray-50 text-gray-400 border-gray-200 cursor-not-allowed'
              : 'bg-teal-600 text-white border-teal-600 hover:bg-teal-700'
          }`}
        >
          {applied && <Check size={12} />}
          {applied ? 'Added to My Plan' : 'Add all to My Plan'}
        </button>
        {applied && canUndo && (
          <button
            type="button"
            onClick={onUndo}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-semibold border bg-white text-gray-700 border-gray-200 hover:bg-gray-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-500 focus-visible:ring-offset-1"
          >
            <Undo2 size={12} />Undo
          </button>
        )}
      </div>
      <div aria-live="polite" className="text-xs mt-1.5 empty:hidden">
        {disabledReason ? (
          <p className="text-amber-700">{disabledReason}</p>
        ) : conflicts.length > 0 ? (
          <p className="text-gray-500">Replaces your current {joinLabels(conflicts)}.</p>
        ) : applied ? (
          <p className="text-emerald-700">Added to My Plan</p>
        ) : null}
      </div>
    </div>
  )
}
