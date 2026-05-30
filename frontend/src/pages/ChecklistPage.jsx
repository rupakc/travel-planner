import { useState, useEffect, useMemo } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import {
  ArrowLeft,
  CheckCircle2,
  Circle,
  AlertCircle,
  ChevronDown,
  ChevronUp,
  ExternalLink,
  Loader2,
  Calendar,
} from 'lucide-react'

// ── bucket helpers ──────────────────────────────────────────────────────────

const BUCKETS = [
  { key: '90+',   label: '3+ Months Before',   min: 90,  max: Infinity },
  { key: '30-89', label: '1–3 Months Before',   min: 30,  max: 89      },
  { key: '14-29', label: '2 Weeks Before',       min: 14,  max: 29      },
  { key: '7-13',  label: '1 Week Before',        min: 7,   max: 13      },
  { key: '1-6',   label: 'Days Before',          min: 1,   max: 6       },
  { key: '0',     label: 'Day of Departure',     min: 0,   max: 0       },
]

function getBucket(daysBefore) {
  for (const b of BUCKETS) {
    if (daysBefore >= b.min && daysBefore <= b.max) return b.key
  }
  return '0'
}

// ── priority helpers ────────────────────────────────────────────────────────

const PRIORITY_STYLES = {
  critical:  { dot: 'bg-red-500',   badge: 'bg-red-50 text-red-700 ring-1 ring-red-200',  label: 'Critical'  },
  important: { dot: 'bg-amber-400', badge: 'bg-amber-50 text-amber-700 ring-1 ring-amber-200', label: 'Important' },
  optional:  { dot: 'bg-gray-300',  badge: 'bg-gray-50 text-gray-500 ring-1 ring-gray-200',  label: 'Optional'  },
}

function priorityStyle(priority) {
  return PRIORITY_STYLES[priority] ?? PRIORITY_STYLES.optional
}

// ── filter tabs ─────────────────────────────────────────────────────────────

const FILTERS = [
  { key: 'all',       label: 'All'       },
  { key: 'critical',  label: 'Critical'  },
  { key: 'remaining', label: 'Remaining' },
]

// ── main component ──────────────────────────────────────────────────────────

export default function ChecklistPage() {
  const { planId } = useParams()
  const navigate   = useNavigate()
  const { token }  = useAuth()

  const storageKey = `checklist_${planId}`

  const [plan,      setPlan]      = useState(null)
  const [items,     setItems]     = useState([])
  const [checked,   setChecked]   = useState(() => {
    try { return JSON.parse(localStorage.getItem(storageKey) || '{}') }
    catch { return {} }
  })
  const [loading,   setLoading]   = useState(true)
  const [error,     setError]     = useState(null)
  const [filter,    setFilter]    = useState('all')
  const [collapsed, setCollapsed] = useState({})

  // ── data fetching ─────────────────────────────────────────────────────────

  useEffect(() => {
    if (!token || !planId) return

    const headers = { Authorization: `Bearer ${token}` }

    async function load() {
      setLoading(true)
      setError(null)
      try {
        // 1. fetch the plan
        const planRes = await fetch(`/api/plans/${planId}`, { headers })
        if (!planRes.ok) throw new Error(`Could not load plan (${planRes.status})`)
        const planData = await planRes.json()
        setPlan(planData)

        // 2. fetch the checklist using the plan's search_data
        const clRes = await fetch('/api/checklist', {
          method:  'POST',
          headers: { ...headers, 'Content-Type': 'application/json' },
          body:    JSON.stringify(planData.search_data ?? {}),
        })
        if (!clRes.ok) throw new Error(`Could not load checklist (${clRes.status})`)
        const clData = await clRes.json()
        setItems(Array.isArray(clData.items) ? clData.items : Array.isArray(clData) ? clData : [])
      } catch (err) {
        setError(err.message)
      } finally {
        setLoading(false)
      }
    }

    load()
  }, [token, planId])

  // ── persist checked state ─────────────────────────────────────────────────

  useEffect(() => {
    localStorage.setItem(storageKey, JSON.stringify(checked))
  }, [checked, storageKey])

  const toggle = (id) =>
    setChecked(prev => ({ ...prev, [id]: !prev[id] }))

  // ── derived values ────────────────────────────────────────────────────────

  const daysUntil = useMemo(() => {
    if (!plan?.search_data?.departure_date) return null
    const dep  = new Date(plan.search_data.departure_date)
    const now  = new Date()
    now.setHours(0, 0, 0, 0)
    dep.setHours(0, 0, 0, 0)
    return Math.round((dep - now) / 86_400_000)
  }, [plan])

  const filteredItems = useMemo(() => {
    if (filter === 'critical')  return items.filter(i => i.priority === 'critical')
    if (filter === 'remaining') return items.filter(i => !checked[i.id])
    return items
  }, [items, filter, checked])

  const grouped = useMemo(() => {
    const map = {}
    for (const b of BUCKETS) map[b.key] = []
    for (const item of filteredItems) {
      const key = getBucket(item.days_before_departure ?? 0)
      map[key].push(item)
    }
    return map
  }, [filteredItems])

  const totalCount    = items.length
  const checkedCount  = items.filter(i => checked[i.id]).length
  const criticalItems = items.filter(i => i.priority === 'critical')
  const allCriticalDone =
    criticalItems.length > 0 && criticalItems.every(i => checked[i.id])
  const progressPct = totalCount > 0 ? Math.round((checkedCount / totalCount) * 100) : 0

  const toggleBucket = (key) =>
    setCollapsed(prev => ({ ...prev, [key]: !prev[key] }))

  // ── loading / error states ────────────────────────────────────────────────

  if (loading) {
    return (
      <div className="flex flex-col items-center justify-center h-[60vh] gap-3 text-gray-400">
        <Loader2 className="animate-spin" size={32} />
        <p className="text-sm">Loading your checklist…</p>
      </div>
    )
  }

  if (error) {
    return (
      <div className="max-w-xl mx-auto px-4 py-16 text-center">
        <AlertCircle className="mx-auto mb-3 text-red-400" size={40} />
        <p className="text-gray-700 font-medium mb-1">Could not load checklist</p>
        <p className="text-sm text-gray-400 mb-6">{error}</p>
        <button
          onClick={() => navigate(-1)}
          className="inline-flex items-center gap-2 px-4 py-2 bg-teal-600 text-white text-sm font-semibold rounded-xl hover:bg-teal-700 transition-all"
        >
          <ArrowLeft size={14} /> Go Back
        </button>
      </div>
    )
  }

  // ── render ────────────────────────────────────────────────────────────────

  const destination = plan?.search_data?.destination ?? 'your trip'
  const tripLabel   = plan?.name ?? `Trip to ${destination}`

  return (
    <div className="max-w-2xl mx-auto px-4 pb-16">

      {/* ── gradient header ── */}
      <div className="relative -mx-4 mb-6 px-6 pt-8 pb-6 bg-gradient-to-br from-teal-500 to-cyan-600 text-white rounded-b-3xl shadow-lg">
        <button
          onClick={() => navigate(-1)}
          className="flex items-center gap-1.5 text-white/80 hover:text-white text-sm font-medium mb-4 transition-colors"
        >
          <ArrowLeft size={16} /> Back
        </button>

        <h1 className="font-display text-2xl font-bold leading-tight mb-0.5">{tripLabel}</h1>
        <p className="text-white/70 text-sm">Pre-departure checklist</p>

        {/* departure countdown */}
        <div className="mt-4 flex items-center gap-2">
          <Calendar size={16} className="text-white/80 shrink-0" />
          {daysUntil === null ? (
            <span className="text-sm text-white/70">No departure date set</span>
          ) : daysUntil < 0 ? (
            <span className="text-sm text-white/80">Departure was {Math.abs(daysUntil)} day{Math.abs(daysUntil) !== 1 ? 's' : ''} ago</span>
          ) : daysUntil === 0 ? (
            <span className="text-sm font-semibold text-yellow-200">Today is departure day!</span>
          ) : (
            <span className="text-sm font-semibold">
              <span className="text-xl font-bold">{daysUntil}</span>
              {' '}day{daysUntil !== 1 ? 's' : ''} until departure
            </span>
          )}
        </div>

        {/* progress bar */}
        <div className="mt-4">
          <div className="flex items-center justify-between text-xs text-white/80 mb-1.5">
            <span>{checkedCount} of {totalCount} complete</span>
            <span>{progressPct}%</span>
          </div>
          <div className="w-full h-2 bg-white/25 rounded-full overflow-hidden">
            <div
              className="h-full bg-white rounded-full transition-all duration-500"
              style={{ width: `${progressPct}%` }}
            />
          </div>
        </div>
      </div>

      {/* ── celebration banner ── */}
      {allCriticalDone && (
        <div className="mb-5 flex items-center gap-3 px-5 py-3.5 bg-green-50 border border-green-200 rounded-2xl shadow-sm">
          <CheckCircle2 size={22} className="text-green-500 shrink-0" />
          <div>
            <p className="text-sm font-semibold text-green-800">All critical items done!</p>
            <p className="text-xs text-green-600">You're well prepared for your trip.</p>
          </div>
        </div>
      )}

      {/* ── filter tabs ── */}
      <div className="mb-5 flex gap-2">
        {FILTERS.map(f => (
          <button
            key={f.key}
            onClick={() => setFilter(f.key)}
            className={`px-4 py-1.5 rounded-full text-sm font-medium border-2 transition-all ${
              filter === f.key
                ? 'bg-teal-600 border-teal-600 text-white shadow-sm'
                : 'bg-white border-gray-200 text-gray-600 hover:border-teal-300 hover:text-teal-600'
            }`}
          >
            {f.label}
            {f.key === 'remaining' && (
              <span className="ml-1.5 text-xs opacity-80">
                ({items.filter(i => !checked[i.id]).length})
              </span>
            )}
          </button>
        ))}
      </div>

      {/* ── empty state ── */}
      {filteredItems.length === 0 && (
        <div className="text-center py-16 text-gray-400">
          <CheckCircle2 size={40} className="mx-auto mb-3 text-teal-300" />
          <p className="font-medium text-gray-600 mb-1">
            {filter === 'remaining' ? 'All items checked off!' : 'No items found'}
          </p>
          <p className="text-sm">
            {filter === 'remaining'
              ? "Nothing left to do — you're all set."
              : 'Your checklist is empty for this filter.'}
          </p>
        </div>
      )}

      {/* ── bucket groups ── */}
      {BUCKETS.map(bucket => {
        const bucketItems = grouped[bucket.key]
        if (!bucketItems || bucketItems.length === 0) return null

        const isCollapsed = collapsed[bucket.key]
        const bucketChecked = bucketItems.filter(i => checked[i.id]).length

        return (
          <div key={bucket.key} className="mb-4">
            {/* bucket header */}
            <button
              onClick={() => toggleBucket(bucket.key)}
              className="w-full flex items-center justify-between px-4 py-2.5 bg-gray-50 hover:bg-gray-100 border border-gray-200 rounded-2xl transition-colors group"
            >
              <div className="flex items-center gap-2.5">
                <span className="font-semibold text-sm text-slate-700">{bucket.label}</span>
                <span className="text-xs text-gray-400 font-medium">
                  {bucketChecked}/{bucketItems.length}
                </span>
              </div>
              <div className="text-gray-400 group-hover:text-gray-600 transition-colors">
                {isCollapsed ? <ChevronDown size={16} /> : <ChevronUp size={16} />}
              </div>
            </button>

            {/* items list */}
            {!isCollapsed && (
              <div className="mt-2 bg-white rounded-2xl shadow-sm ring-1 ring-gray-100 divide-y divide-gray-50">
                {bucketItems.map((item, idx) => {
                  const isChecked = !!checked[item.id]
                  const ps        = priorityStyle(item.priority)

                  return (
                    <div
                      key={item.id ?? idx}
                      className={`flex items-start gap-3 px-5 py-4 transition-colors ${
                        isChecked ? 'bg-gray-50/60' : 'hover:bg-gray-50/40'
                      } ${idx === 0 ? 'rounded-t-2xl' : ''} ${
                        idx === bucketItems.length - 1 ? 'rounded-b-2xl' : ''
                      }`}
                    >
                      {/* checkbox */}
                      <button
                        onClick={() => toggle(item.id ?? idx)}
                        className="mt-0.5 shrink-0 text-teal-500 hover:text-teal-600 transition-colors"
                        aria-label={isChecked ? 'Mark incomplete' : 'Mark complete'}
                      >
                        {isChecked
                          ? <CheckCircle2 size={20} className="text-teal-500" />
                          : <Circle      size={20} className="text-gray-300" />
                        }
                      </button>

                      {/* priority dot */}
                      <span className={`mt-2 shrink-0 w-2 h-2 rounded-full ${ps.dot}`} />

                      {/* content */}
                      <div className="flex-1 min-w-0">
                        <div className="flex flex-wrap items-center gap-2 mb-0.5">
                          {/* title — link if url present */}
                          {item.link_url ? (
                            <a
                              href={item.link_url}
                              target="_blank"
                              rel="noopener noreferrer"
                              className={`text-sm font-semibold text-teal-700 hover:underline flex items-center gap-1 ${
                                isChecked ? 'line-through opacity-50' : ''
                              }`}
                            >
                              {item.title}
                              <ExternalLink size={12} className="shrink-0" />
                            </a>
                          ) : (
                            <span className={`text-sm font-semibold text-slate-800 ${isChecked ? 'line-through opacity-40' : ''}`}>
                              {item.title}
                            </span>
                          )}

                          {/* priority badge */}
                          <span className={`px-2 py-0.5 rounded-full text-[10px] font-semibold ${ps.badge}`}>
                            {ps.label}
                          </span>
                        </div>

                        {item.description && (
                          <p className={`text-xs text-gray-500 leading-relaxed ${isChecked ? 'opacity-40' : ''}`}>
                            {item.description}
                          </p>
                        )}
                      </div>
                    </div>
                  )
                })}
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}
