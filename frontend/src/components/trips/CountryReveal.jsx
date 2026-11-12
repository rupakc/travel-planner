import { useTranslation } from 'react-i18next'

const reduced = () => {
  try { return window.matchMedia('(prefers-reduced-motion: reduce)').matches } catch { return false }
}

const CSS = `
.recap-stamp { animation: recapStamp .55s cubic-bezier(.2,.8,.3,1.2) both; }
@keyframes recapStamp {
  0% { opacity: 0; transform: scale(1.8) rotate(-14deg); }
  70% { opacity: 1; transform: scale(.95) rotate(-4deg); }
  100% { opacity: 1; transform: scale(1) rotate(-4deg); }
}
@media (prefers-reduced-motion: reduce) { .recap-stamp { animation: none; } }
`

/** One passport stamp per new country; a plain list under reduced motion. */
export default function CountryReveal({ countries, onClose }) {
  const { t } = useTranslation('recap')
  if (!countries?.length) return null
  const list = reduced()
  return (
    <div className="rounded-2xl border border-teal-200 bg-teal-50 p-4"
      role="status" data-tid="recap.reveal">
      <style>{CSS}</style>
      <h3 className="font-semibold text-teal-900">{t('reveal.title', { count: countries.length })}</h3>
      {list ? (
        <ul className="mt-2 list-disc pl-5 text-sm text-teal-900" data-tid="recap.reveal-list">
          {countries.map((c) => <li key={c.code}>{c.name}</li>)}
        </ul>
      ) : (
        <div className="mt-3 flex flex-wrap gap-3">
          {countries.map((c, i) => (
            <div key={c.code} data-tid={`recap.stamp-${c.code}`}
              className="recap-stamp rounded-lg border-4 border-double border-teal-700 px-4 py-2 text-center text-teal-800"
              style={{ animationDelay: `${i * 250}ms` }}>
              <div className="text-xs font-bold uppercase tracking-widest">{c.code}</div>
              <div className="text-sm font-semibold">{c.name}</div>
            </div>
          ))}
        </div>
      )}
      <button type="button" onClick={onClose} data-tid="recap.reveal-close"
        className="mt-3 min-h-[44px] rounded-lg px-3 text-sm font-medium text-teal-800 underline">
        {t('reveal.close')}
      </button>
    </div>
  )
}
