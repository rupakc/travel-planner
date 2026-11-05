import { rowBadge } from '../../utils/tripWatch'

const TONES = {
  emerald: 'bg-emerald-50 text-emerald-800 border-emerald-200',
  sky: 'bg-sky-50 text-sky-800 border-sky-200',
  amber: 'bg-amber-50 text-amber-800 border-amber-200',
  slate: 'bg-slate-100 text-slate-600 border-slate-200',
}

/** Live / Estimate (or degraded) badge for one part of a watched trip. */
export default function TripBadge({ row }) {
  const b = rowBadge(row)
  return (
    <span title={b.title} className={`inline-flex shrink-0 items-center rounded-full border px-1.5 py-px text-[10px] font-medium ${TONES[b.tone]}`}>
      {b.label}
      <span className="sr-only">: {b.title}</span>
    </span>
  )
}
