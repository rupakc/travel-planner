import { useState } from 'react'
import { Wallet, ChevronDown, RotateCcw, Loader2 } from 'lucide-react'

const usd = (n) => `$${Math.round(Number(n) || 0).toLocaleString()}`
const plural = (n, one, many) => (n === 1 ? one : many)

// Literal class names so Tailwind keeps them; hues match CostBreakdown
const CATEGORIES = [
  { key: 'flights', label: 'Flights', noun: 'flights', bar: 'bg-sky-500', accent: 'accent-sky-500' },
  { key: 'stay', label: 'Stay', noun: 'stay', bar: 'bg-purple-500', accent: 'accent-purple-500' },
  { key: 'activities', label: 'Activities', noun: 'activities', bar: 'bg-green-500', accent: 'accent-green-500' },
]
const OTHER_BAR = 'bg-gray-300'
const MIN_HOTELS_FITTING = 3
const NARROW = '(max-width: 639px)'

function fitText(key, fit) {
  if (key === 'flights') {
    const { count, total } = fit.flights
    return `${count} of ${total} ${plural(total, 'flight fits', 'flights fit')}`
  }
  if (key === 'stay') {
    const { count, total } = fit.hotels
    return `${count} of ${total} ${plural(total, 'hotel fits', 'hotels fit')}`
  }
  const n = fit.activities.picked.size
  return `Fits ${n} ${plural(n, 'activity', 'activities')} (${usd(fit.activities.spent)})`
}

function announcement(key, allocation, fit) {
  if (!key) return ''
  const name = { flights: 'Flight', stay: 'Stay', activities: 'Activities' }[key]
  const what = fitText(key, fit)
  return `${name} budget ${usd(allocation[key])} — ${key === 'activities' ? what.charAt(0).toLowerCase() + what.slice(1) : what}`
}

/**
 * Splits the trip budget into per-person shares and shows which loaded
 * results fit each one. All state lives in the parent; this only renders.
 */
export default function BudgetPlanner({
  allocation,
  fit,
  onChange,
  onTotalChange,
  onReset,
  showOnlyFits,
  onShowOnlyFitsChange,
  onFindCheaperHotels,
  findingCheaperHotels,
}) {
  // Expanded on desktop, collapsed on phones; checked once on mount
  const [open, setOpen] = useState(
    () => !(typeof window !== 'undefined' && typeof window.matchMedia === 'function' && window.matchMedia(NARROW)?.matches),
  )
  const [draftTotal, setDraftTotal] = useState(null)
  const [lastMoved, setLastMoved] = useState(null)

  const total = allocation.flights + allocation.stay + allocation.activities + allocation.other
  const parts = [...CATEGORIES.map((c) => ({ ...c, amount: allocation[c.key] })), { key: 'other', label: 'Everything else', bar: OTHER_BAR, amount: allocation.other }]
  const maxNightly = fit.nights > 0 ? Math.floor(allocation.stay / fit.nights) : 0
  const offerCheaperHotels = fit.hotels.count < MIN_HOTELS_FITTING && maxNightly >= 1

  const commitTotal = () => {
    if (draftTotal === null) return
    const n = Number(draftTotal)
    setDraftTotal(null)
    if (draftTotal.trim() !== '' && Number.isFinite(n) && n > 0 && Math.round(n) !== total) onTotalChange(Math.round(n))
  }

  return (
    <section className="bg-white rounded-xl shadow-md border border-gray-100 ring-1 ring-black/5 p-4" aria-labelledby="budget-planner-heading">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        aria-controls="budget-planner-body"
        className="w-full flex items-center gap-2 text-left rounded-lg focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-500"
      >
        <span className="w-7 h-7 shrink-0 rounded-lg bg-gradient-to-br from-sky-500 to-purple-500 flex items-center justify-center">
          <Wallet size={14} className="text-white" />
        </span>
        <span className="min-w-0 flex-1">
          <span id="budget-planner-heading" className="block text-sm font-bold text-gray-800">Budget planner</span>
          <span className="block text-xs text-gray-500">Split your budget and see which options fit</span>
        </span>
        <ChevronDown size={16} className={`shrink-0 text-gray-400 transition-transform ${open ? 'rotate-180' : ''}`} aria-hidden="true" />
      </button>

      {open && (
        <div id="budget-planner-body" className="mt-3">
          <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
            <label htmlFor="budget-planner-total" className="text-xs font-semibold text-gray-600">Total budget</label>
            <div className="flex items-center gap-1">
              <span className="text-sm text-gray-500" aria-hidden="true">$</span>
              <input
                id="budget-planner-total"
                type="number"
                min="1"
                inputMode="numeric"
                value={draftTotal ?? String(total)}
                onChange={(e) => setDraftTotal(e.target.value)}
                onBlur={commitTotal}
                onKeyDown={(e) => { if (e.key === 'Enter') commitTotal() }}
                className="w-28 px-2 py-1 text-sm font-semibold text-gray-900 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-teal-500"
              />
            </div>
            <span className="text-xs text-gray-400">per person</span>
            <button
              type="button"
              onClick={onReset}
              className="ml-auto flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-semibold border bg-white text-gray-600 border-gray-200 hover:bg-gray-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-500"
            >
              <RotateCcw size={11} /> Reset
            </button>
          </div>

          <div
            className="mt-3 flex h-2.5 rounded-full overflow-hidden bg-gray-100 gap-px"
            role="img"
            aria-label={parts.map((p) => `${p.label} ${usd(p.amount)}`).join(', ')}
          >
            {parts.map((p) => (
              <div key={p.key} className={p.bar} style={{ width: `${total > 0 ? (p.amount / total) * 100 : 0}%` }} />
            ))}
          </div>

          <div className="mt-3 grid grid-cols-1 sm:grid-cols-3 gap-4">
            {CATEGORIES.map((c) => {
              const id = `budget-planner-${c.key}`
              return (
                <div key={c.key} className="min-w-0">
                  <div className="flex items-center justify-between gap-2">
                    <label htmlFor={id} className="flex items-center gap-1.5 text-xs font-semibold text-gray-700">
                      <span className={`w-2 h-2 rounded-full ${c.bar}`} aria-hidden="true" />
                      {c.label}
                    </label>
                    <span className="text-sm font-bold text-gray-900 tabular-nums">{usd(allocation[c.key])}</span>
                  </div>
                  <input
                    id={id}
                    data-key={c.key}
                    type="range"
                    min="0"
                    max={total}
                    step="10"
                    value={allocation[c.key]}
                    aria-valuetext={`${usd(allocation[c.key])} for ${c.noun}`}
                    onChange={(e) => {
                      setLastMoved(c.key)
                      onChange(c.key, Number(e.target.value))
                    }}
                    className={`w-full mt-1 cursor-pointer ${c.accent}`}
                  />
                  <p className="text-xs text-gray-500">{fitText(c.key, fit)}</p>
                  {c.key === 'stay' && offerCheaperHotels && (
                    <button
                      type="button"
                      onClick={() => onFindCheaperHotels(maxNightly)}
                      disabled={findingCheaperHotels}
                      className="mt-1.5 flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-semibold border bg-purple-50 text-purple-700 border-purple-200 hover:bg-purple-100 disabled:opacity-60 disabled:cursor-not-allowed focus:outline-none focus-visible:ring-2 focus-visible:ring-purple-500"
                    >
                      {findingCheaperHotels ? <><Loader2 size={11} className="animate-spin" /> Finding cheaper hotels…</> : 'Find cheaper hotels'}
                    </button>
                  )}
                </div>
              )
            })}
          </div>

          <div className="mt-3 flex items-center justify-between gap-2 border-t border-gray-100 pt-2">
            <span className="flex items-center gap-1.5 text-xs text-gray-700 min-w-0">
              <span className={`w-2 h-2 shrink-0 rounded-full ${OTHER_BAR}`} aria-hidden="true" />
              <span className="font-semibold">Everything else</span>
              <span className="text-gray-400 truncate">food, transport, extras</span>
            </span>
            <span className="text-sm font-bold text-gray-900 tabular-nums">{usd(allocation.other)}</span>
          </div>

          <div className="mt-3 flex items-center gap-2">
            <button
              type="button"
              role="switch"
              aria-checked={showOnlyFits}
              onClick={() => onShowOnlyFitsChange(!showOnlyFits)}
              className="flex items-center gap-2 text-xs font-semibold text-gray-700 rounded focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-500"
            >
              <span className={`relative inline-block w-8 h-4 rounded-full transition-colors ${showOnlyFits ? 'bg-teal-600' : 'bg-gray-300'}`} aria-hidden="true">
                <span className={`absolute top-0.5 w-3 h-3 rounded-full bg-white shadow transition-all ${showOnlyFits ? 'left-4' : 'left-0.5'}`} />
              </span>
              Show only what fits
            </button>
          </div>
        </div>
      )}

      <p aria-live="polite" className="sr-only">{announcement(lastMoved, allocation, fit)}</p>
    </section>
  )
}
