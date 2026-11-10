import { useId } from 'react'
import { useTranslation } from 'react-i18next'
import { fmtDate, fmtNumber } from '../../i18n/format'

const DAYS = 30
const DAY_MS = 24 * 3600e3

// One entry per UTC day for the last `n` days ending today; days the backend
// left out (no events) count as zero so the chart's x axis is continuous.
export function fillDays(days, n = DAYS, now = new Date()) {
  const byDay = Object.fromEntries((days || []).map((d) => [d.day, d]))
  const end = Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate())
  const out = []
  for (let i = n - 1; i >= 0; i--) {
    const day = new Date(end - i * DAY_MS).toISOString().slice(0, 10)
    out.push(byDay[day] || { day, users: 0, sessions: 0, events: 0 })
  }
  return out
}

const dateLabel = (day) => fmtDate(`${day}T00:00:00Z`, { month: 'short', day: 'numeric', timeZone: 'UTC' })

function Tile({ tid, label, value }) {
  return (
    <div data-tid={tid} className="p-4 bg-white border border-gray-200 rounded-xl">
      <p className="text-xs text-gray-500">{label}</p>
      <p className="font-display text-2xl font-bold text-gray-800 mt-1">{fmtNumber(value)}</p>
    </div>
  )
}

// Single-series bar chart. Colours come from theme tokens (Tailwind classes
// backed by CSS variables), so it reads in light and dark.
function UsersChart({ days }) {
  const { t } = useTranslation('adminTelemetry')
  const id = useId()
  const W = 600, H = 160, L = 36, R = 8, T = 12, B = 22
  const max = Math.max(1, ...days.map((d) => d.users))
  const slot = (W - L - R) / days.length
  const barH = (v) => ((H - T - B) * v) / max
  const first = dateLabel(days[0].day)
  const last = dateLabel(days[days.length - 1].day)
  const peakDay = days.reduce((p, d) => (d.users > p.users ? d : p), days[0])
  const title = t('chartTitle')
  const desc = t('chartSummary', {
    from: first, to: last, max: fmtNumber(Math.max(...days.map((d) => d.users))), peak: dateLabel(peakDay.day),
  })
  return (
    <svg role="img" aria-labelledby={`${id}-t ${id}-d`} viewBox={`0 0 ${W} ${H}`} className="w-full h-auto">
      <title id={`${id}-t`}>{title}</title>
      <desc id={`${id}-d`}>{desc}</desc>
      <line x1={L} x2={W - R} y1={T} y2={T} className="stroke-gray-200" strokeWidth="1" strokeDasharray="3 3" />
      <line x1={L} x2={W - R} y1={H - B} y2={H - B} className="stroke-gray-300" strokeWidth="1" />
      <text x={L - 6} y={T + 4} textAnchor="end" fontSize="11" className="fill-gray-500">{fmtNumber(max)}</text>
      <text x={L - 6} y={H - B + 4} textAnchor="end" fontSize="11" className="fill-gray-500">0</text>
      {days.map((d, i) => (
        <rect key={d.day} x={L + i * slot + 1} y={H - B - barH(d.users)} width={Math.max(1, slot - 2)}
          height={barH(d.users)} rx="1.5" className="fill-teal-600" />
      ))}
      <text x={L} y={H - 6} fontSize="11" className="fill-gray-500">{first}</text>
      <text x={W - R} y={H - 6} textAnchor="end" fontSize="11" className="fill-gray-500">{last}</text>
    </svg>
  )
}

function Table({ title, cols, rows, empty }) {
  return (
    <div>
      <h3 className="text-sm font-semibold text-gray-700 mb-2">{title}</h3>
      <div className="overflow-x-auto rounded-xl border border-gray-200">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 text-gray-600 text-xs uppercase">
            <tr>
              <th className="px-4 py-2 text-left">{cols[0]}</th>
              <th className="px-4 py-2 text-right">{cols[1]}</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {rows.length === 0 ? (
              <tr><td colSpan={2} className="px-4 py-3 text-gray-400">{empty}</td></tr>
            ) : rows.map(([k, n]) => (
              <tr key={k}>
                <td className="px-4 py-2 font-mono text-xs text-gray-700 break-all">{k}</td>
                <td className="px-4 py-2 text-right tabular-nums">{fmtNumber(n)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

// Presentational: AdminPage owns the fetch (it needs the 404 to hide the tab).
export default function TelemetrySummary({ summary, error }) {
  const { t } = useTranslation('adminTelemetry')
  if (error) {
    return (
      <p role="alert" data-tid="admin.telemetry-error"
        className="text-sm text-red-600 bg-red-50 border border-red-200 rounded-lg px-3 py-2">
        {t('error')}
      </p>
    )
  }
  if (!summary) return <p className="text-sm text-gray-400">{t('loading')}</p>

  const days = fillDays(summary.days)
  const today = days[days.length - 1]
  const week = days.slice(-7).reduce((s, d) => s + d.users, 0)
  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
        <Tile tid="admin.telemetry-users-today" label={t('usersToday')} value={today.users} />
        <Tile tid="admin.telemetry-sessions-today" label={t('sessionsToday')} value={today.sessions} />
        <Tile tid="admin.telemetry-users-7d" label={t('users7d')} value={week} />
      </div>
      <div className="p-4 bg-white border border-gray-200 rounded-xl">
        <h3 className="text-sm font-semibold text-gray-700 mb-2">{t('chartTitle')}</h3>
        <UsersChart days={days} />
      </div>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        <Table title={t('topEvents')} cols={[t('colEvent'), t('colEvents')]} empty={t('empty')}
          rows={(summary.top_events || []).map((e) => [e.event, e.events])} />
        <Table title={t('topScreens')} cols={[t('colScreen'), t('colViews')]} empty={t('empty')}
          rows={(summary.top_screens || []).map((s) => [s.route, s.views])} />
      </div>
    </div>
  )
}
