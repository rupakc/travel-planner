import { useMemo, useState } from 'react'

const TIME_ROWS = [
  { key: 'morning',   label: 'Morning',   icon: '🌅', color: 'border-sky-400 bg-sky-50',   text: 'text-sky-700' },
  { key: 'afternoon', label: 'Afternoon', icon: '☀️', color: 'border-teal-400 bg-teal-50', text: 'text-teal-700' },
  { key: 'evening',   label: 'Evening',   icon: '🌙', color: 'border-indigo-400 bg-indigo-50', text: 'text-indigo-700' },
]

const WMO_EMOJI = {
  0: '☀️', 1: '🌤️', 2: '⛅', 3: '☁️',
  45: '🌫️', 48: '🌫️',
  51: '🌦️', 53: '🌧️', 55: '🌧️',
  61: '🌧️', 63: '🌧️', 65: '🌧️',
  71: '🌨️', 73: '🌨️', 75: '❄️',
  80: '🌦️', 81: '🌧️', 82: '⛈️',
  95: '⛈️', 96: '⛈️', 99: '⛈️',
}

function normalizeTimeOfDay(str) {
  if (!str) return 'other'
  const s = str.toLowerCase()
  if (s.includes('morning')) return 'morning'
  if (s.includes('afternoon')) return 'afternoon'
  if (s.includes('evening') || s.includes('night')) return 'evening'
  return 'other'
}

function ActivityBlock({ slot, rowColor, rowText }) {
  return (
    <div className={`border-l-4 ${rowColor} rounded-r-lg p-2 text-xs flex flex-col gap-0.5 min-h-[56px]`}>
      <span className={`font-semibold ${rowText} line-clamp-2 leading-snug`} title={slot.activity}>
        {slot.activity}
      </span>
      {slot.location && (
        <span className="text-gray-500 line-clamp-1 text-[11px]">{slot.location}</span>
      )}
      {slot.estimated_cost_usd != null && (
        <span className="text-gray-400 text-[11px]">${slot.estimated_cost_usd}</span>
      )}
    </div>
  )
}

function EmptyCell() {
  return (
    <div className="border border-dashed border-gray-200 rounded-lg min-h-[56px] bg-gray-50 flex items-center justify-center text-gray-300 text-xs">
      —
    </div>
  )
}

function MobileView({ days, weatherMap }) {
  return (
    <div className="space-y-4">
      <div className="bg-amber-50 border border-amber-200 rounded-lg px-3 py-2 text-xs text-amber-700">
        📱 Timeline view is best on desktop — showing compact day list
      </div>
      {days.map((day, i) => {
        const w = weatherMap.get(day.date)
        return (
          <div key={i} className="border border-gray-200 rounded-xl p-3 space-y-2">
            <div className="flex items-center justify-between">
              <span className="text-sm font-semibold text-gray-800">
                {new Date(day.date + 'T12:00:00').toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric' })}
              </span>
              {w && (
                <span className="text-xs text-gray-500">
                  {WMO_EMOJI[w.weather_code] || '🌡️'} {Math.round(w.temp_high_c ?? 0)}°/{Math.round(w.temp_low_c ?? 0)}°C
                </span>
              )}
            </div>
            <div className="flex flex-wrap gap-1.5">
              {(day.slots || []).map((slot, j) => (
                <span key={j} className="text-xs bg-gray-100 text-gray-700 px-2 py-0.5 rounded-full">
                  {slot.activity}
                </span>
              ))}
            </div>
          </div>
        )
      })}
    </div>
  )
}

export default function TimelineView({ itineraryData, weatherData }) {
  const [isMobile] = useState(() => window.innerWidth < 768)

  const days = itineraryData?.days || []
  const weatherDays = weatherData?.days || []

  const weatherMap = useMemo(() => {
    const m = new Map()
    for (const w of weatherDays) m.set(w.date, w)
    return m
  }, [weatherDays])

  const slotGrid = useMemo(() => {
    return days.map(day => {
      const byTime = { morning: null, afternoon: null, evening: null, other: [] }
      for (const slot of (day.slots || [])) {
        const key = normalizeTimeOfDay(slot.time_of_day)
        if (key === 'other') byTime.other.push(slot)
        else byTime[key] = slot
      }
      return { day, byTime }
    })
  }, [days])

  if (!days.length) return null

  if (isMobile) return <MobileView days={days} weatherMap={weatherMap} />

  return (
    <div className="relative">
      {/* Scroll container */}
      <div className="overflow-x-auto pb-2"
        style={{
          background: 'linear-gradient(to right, white 0%, transparent 2%, transparent 98%, white 100%)',
        }}>
        <div className="flex min-w-max">
          {/* Row labels */}
          <div className="sticky left-0 z-10 bg-white border-r border-gray-100 shrink-0 w-24">
            <div className="h-14 border-b border-gray-100" /> {/* header spacer */}
            {TIME_ROWS.map(row => (
              <div key={row.key} className="h-20 flex items-center px-2 border-b border-gray-100">
                <span className="text-xs font-medium text-gray-500">
                  {row.icon} {row.label}
                </span>
              </div>
            ))}
          </div>

          {/* Day columns */}
          {slotGrid.map(({ day, byTime }, i) => {
            const w = weatherMap.get(day.date)
            const dateLabel = new Date(day.date + 'T12:00:00').toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric' })
            return (
              <div key={i} className="min-w-[176px] border-r border-gray-100 shrink-0">
                {/* Day header */}
                <div className="h-14 px-2 py-2 border-b border-gray-100 flex flex-col justify-center">
                  <span className="text-xs font-semibold text-gray-700 block">{dateLabel}</span>
                  {w ? (
                    <span className="text-[11px] text-gray-500">
                      {WMO_EMOJI[w.weather_code] || '🌡️'} {Math.round(w.temp_high_c ?? 0)}°/{Math.round(w.temp_low_c ?? 0)}°C
                    </span>
                  ) : (
                    <span className="text-[11px] text-gray-300">🌡️ —</span>
                  )}
                </div>

                {/* Time slots */}
                {TIME_ROWS.map(row => (
                  <div key={row.key} className="h-20 p-1.5 border-b border-gray-100">
                    {byTime[row.key]
                      ? <ActivityBlock slot={byTime[row.key]} rowColor={row.color} rowText={row.text} />
                      : <EmptyCell />}
                  </div>
                ))}

                {/* Budget bar */}
                {day.daily_estimated_cost_usd != null && (
                  <div className="h-1.5 bg-gray-100 mx-1.5 rounded-full overflow-hidden">
                    <div
                      className="h-full bg-teal-400 rounded-full"
                      style={{ width: `${Math.min(100, (day.daily_estimated_cost_usd / 300) * 100)}%` }}
                    />
                  </div>
                )}
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}
