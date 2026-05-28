import { useMemo, useState } from 'react'
import { ChevronDown } from 'lucide-react'

const TIME_COLS = [
  { key: 'morning',   label: 'Morning',   icon: '🌅', border: 'border-sky-400',    bg: 'bg-sky-50',    text: 'text-sky-700',    dot: 'bg-sky-400' },
  { key: 'afternoon', label: 'Afternoon', icon: '☀️',  border: 'border-teal-400',   bg: 'bg-teal-50',   text: 'text-teal-700',   dot: 'bg-teal-400' },
  { key: 'evening',   label: 'Evening',   icon: '🌙', border: 'border-indigo-400', bg: 'bg-indigo-50', text: 'text-indigo-700', dot: 'bg-indigo-400' },
]

const WMO_EMOJI = {
  0: '☀️', 1: '🌤️', 2: '⛅', 3: '☁️',
  45: '🌫️', 48: '🌫️',
  51: '🌦️', 53: '🌧️', 55: '🌧️',
  61: '🌧️', 63: '🌧️', 65: '🌧️',
  71: '🌨️', 73: '🌨️', 75: '❄️', 77: '❄️',
  80: '🌦️', 81: '🌧️', 82: '⛈️',
  85: '🌨️', 86: '❄️',
  95: '⛈️', 96: '⛈️', 99: '⛈️',
}

function getWeatherGradient(code) {
  if (code == null) return 'from-teal-600 to-teal-700'
  if (code <= 2)  return 'from-amber-400 to-orange-400'
  if (code === 3) return 'from-slate-400 to-slate-500'
  if (code <= 48) return 'from-gray-400 to-gray-500'
  if (code <= 67) return 'from-blue-500 to-blue-600'
  if (code <= 77) return 'from-indigo-400 to-indigo-500'
  if (code <= 82) return 'from-blue-400 to-sky-500'
  return 'from-gray-600 to-gray-700'
}

function normalizeTimeOfDay(str) {
  if (!str) return 'other'
  const s = str.toLowerCase()
  if (s.includes('morning')) return 'morning'
  if (s.includes('afternoon')) return 'afternoon'
  if (s.includes('evening') || s.includes('night')) return 'evening'
  return 'other'
}

function ActivityCard({ slot, col }) {
  const [expanded, setExpanded] = useState(false)
  const hasDetails = slot.notes || slot.duration_hours || slot.estimated_cost_usd != null

  return (
    <div
      onClick={() => hasDetails && setExpanded(e => !e)}
      className={`border-l-4 ${col.border} ${col.bg} rounded-r-lg p-2.5 transition-all ${hasDetails ? 'cursor-pointer hover:brightness-95' : ''}`}
    >
      <p className={`text-xs font-semibold ${col.text} leading-snug line-clamp-2`} title={slot.activity}>
        {slot.activity}
      </p>
      {slot.location && (
        <p className="text-[11px] text-gray-500 mt-0.5 flex items-center gap-0.5">
          <span>📍</span>{slot.location}
        </p>
      )}
      {!expanded && (slot.duration_hours || slot.estimated_cost_usd != null) && (
        <p className="text-[11px] text-gray-400 mt-1">
          {slot.duration_hours ? `⏱ ${slot.duration_hours}h` : ''}
          {slot.duration_hours && slot.estimated_cost_usd != null ? ' · ' : ''}
          {slot.estimated_cost_usd != null ? `$${slot.estimated_cost_usd}` : ''}
        </p>
      )}
      {expanded && (
        <div className="mt-1.5 pt-1.5 border-t border-current/10 space-y-0.5">
          {slot.duration_hours && (
            <p className="text-[11px] text-gray-600">⏱ {slot.duration_hours} hour{slot.duration_hours !== 1 ? 's' : ''}</p>
          )}
          {slot.estimated_cost_usd != null && (
            <p className="text-[11px] text-gray-600">💰 ${slot.estimated_cost_usd} est.</p>
          )}
          {slot.notes && (
            <p className="text-[11px] text-gray-500 italic">{slot.notes}</p>
          )}
        </div>
      )}
      {hasDetails && (
        <p className={`text-[10px] ${col.text} opacity-50 mt-1`}>{expanded ? '▲ less' : '▼ more'}</p>
      )}
    </div>
  )
}

function EmptySlot() {
  return (
    <div className="border border-dashed border-gray-200 rounded-lg p-2.5 min-h-[64px] flex items-center justify-center">
      <span className="text-xs text-gray-300">—</span>
    </div>
  )
}

function DayCard({ dayData, weatherDay }) {
  const [collapsed, setCollapsed] = useState(false)
  const wCode = weatherDay?.weather_code
  const gradient = getWeatherGradient(wCode)

  const byTime = useMemo(() => {
    const m = { morning: null, afternoon: null, evening: null }
    for (const slot of (dayData.slots || [])) {
      const key = normalizeTimeOfDay(slot.time_of_day)
      if (key in m && !m[key]) m[key] = slot
    }
    return m
  }, [dayData.slots])

  const dateLabel = new Date(dayData.date + 'T12:00:00').toLocaleDateString('en-US', {
    weekday: 'long', month: 'short', day: 'numeric',
  })

  return (
    <div className="rounded-2xl overflow-hidden border border-gray-200 shadow-sm">
      {/* Day header */}
      <button
        type="button"
        onClick={() => setCollapsed(c => !c)}
        className={`w-full bg-gradient-to-r ${gradient} text-white px-4 py-3 flex items-center justify-between gap-2 hover:brightness-95 transition-all`}
      >
        <div className="flex items-center gap-3 min-w-0">
          <span className="bg-white/20 text-white text-xs font-bold w-7 h-7 rounded-full flex items-center justify-center shrink-0">
            {dayData.day_number}
          </span>
          <div className="text-left min-w-0">
            <p className="text-sm font-semibold truncate">{dateLabel}</p>
            {dayData.theme && (
              <p className="text-xs text-white/80 truncate">{dayData.theme}</p>
            )}
          </div>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          {weatherDay && (
            <span className="text-xs text-white/90 flex items-center gap-1">
              {WMO_EMOJI[wCode] || '🌡️'} {Math.round(weatherDay.temp_high_c ?? 0)}°/{Math.round(weatherDay.temp_low_c ?? 0)}°C
            </span>
          )}
          <ChevronDown
            size={16}
            className={`text-white/80 transition-transform duration-300 ${collapsed ? '-rotate-90' : ''}`}
          />
        </div>
      </button>

      {/* Content */}
      {!collapsed && (
        <div className="bg-white">
          {/* Column headers */}
          <div className="grid grid-cols-3 border-b border-gray-100">
            {TIME_COLS.map(col => (
              <div key={col.key} className="px-2 py-1.5 text-center">
                <span className="text-xs font-medium text-gray-500">{col.icon} {col.label}</span>
              </div>
            ))}
          </div>

          {/* Activity slots */}
          <div className="grid grid-cols-3 gap-2 p-3">
            {TIME_COLS.map(col => (
              <div key={col.key}>
                {byTime[col.key]
                  ? <ActivityCard slot={byTime[col.key]} col={col} />
                  : <EmptySlot col={col} />}
              </div>
            ))}
          </div>

          {/* Budget bar */}
          {dayData.daily_estimated_cost_usd != null && (
            <div className="px-3 pb-3">
              <div className="flex items-center justify-between text-[11px] text-gray-400 mb-1">
                <span>Est. daily spend</span>
                <span className="font-medium text-gray-600">${dayData.daily_estimated_cost_usd}</span>
              </div>
              <div className="h-1.5 bg-gray-100 rounded-full overflow-hidden">
                <div
                  className="h-full bg-gradient-to-r from-teal-400 to-teal-500 rounded-full transition-all"
                  style={{ width: `${Math.min(100, (dayData.daily_estimated_cost_usd / 300) * 100)}%` }}
                />
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

export default function TimelineView({ itineraryData, weatherData }) {
  const days = itineraryData?.days || []
  const weatherDays = weatherData?.days || []

  const weatherMap = useMemo(() => {
    const m = new Map()
    for (const w of weatherDays) m.set(w.date, w)
    return m
  }, [weatherDays])

  if (!days.length) return null

  return (
    <div className="space-y-3 pb-4">
      {days.map((day, i) => (
        <DayCard
          key={day.date || i}
          dayData={day}
          weatherDay={weatherMap.get(day.date)}
          index={i}
        />
      ))}
    </div>
  )
}
