import { useTranslation } from 'react-i18next'

const BITS = Array.from({ length: 14 }, (_, i) => i)
const COLORS = ['#0f766e', '#f59e0b', '#e11d48', '#4f46e5', '#16a34a']

export function prefersReducedMotion() {
  try { return !!window.matchMedia?.('(prefers-reduced-motion: reduce)').matches } catch { return false }
}

// "Trip ready N %" bar. `celebrate` plays the CSS-only confetti burst once
// (never under reduced motion); at 100 % the bar turns into "Ready to go".
export default function TripReadyBar({ percent = 0, complete = false, celebrate = false }) {
  const { t } = useTranslation('prep')
  const pct = Math.max(0, Math.min(100, Math.floor(percent)))
  const confetti = complete && celebrate && !prefersReducedMotion()
  return (
    <div
      data-tid="prep-ready-bar"
      className={`relative overflow-hidden rounded-xl border p-3 ${complete
        ? 'border-teal-600 bg-teal-50'
        : 'border-slate-200 bg-white'}`}
    >
      <div className="flex items-center justify-between gap-2 text-sm font-semibold text-slate-900">
        <span data-tid="prep-ready-label">{t('ready', { percent: pct })}</span>
        {complete && (
          <span data-tid="prep-ready-go" role="status" className="text-teal-800">{t('go')}</span>
        )}
      </div>
      <div
        role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={pct}
        aria-label={t('ready', { percent: pct })}
        className="mt-2 h-2 rounded-full bg-slate-200"
      >
        <div className="h-2 rounded-full bg-teal-700 transition-[width] motion-reduce:transition-none" style={{ width: `${pct}%` }} />
      </div>
      {confetti && (
        <div className="confetti pointer-events-none absolute inset-0" aria-hidden="true" data-tid="prep-confetti">
          <style>{`
            .confetti i{position:absolute;top:30%;left:50%;width:7px;height:11px;border-radius:2px;opacity:0;animation:prepConfetti 1.1s ease-out forwards}
            @keyframes prepConfetti{0%{opacity:1;transform:translate(0,0) rotate(0)}100%{opacity:0;transform:translate(var(--dx),var(--dy)) rotate(var(--rot))}}
            @media (prefers-reduced-motion: reduce){.confetti{display:none}}
          `}</style>
          {BITS.map((i) => (
            <i
              key={i}
              style={{
                background: COLORS[i % COLORS.length],
                '--dx': `${(i - 6.5) * 22}px`,
                '--dy': `${-50 + (i % 4) * 38}px`,
                '--rot': `${(i % 2 ? 1 : -1) * (180 + i * 20)}deg`,
              }}
            />
          ))}
        </div>
      )}
    </div>
  )
}
