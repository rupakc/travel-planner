import { useTranslation } from 'react-i18next'

const CSS = `
.today-stamp{animation:todayStamp 500ms cubic-bezier(.2,1.4,.4,1) both}
@keyframes todayStamp{from{opacity:0;transform:scale(1.8) rotate(-18deg)}to{opacity:1;transform:scale(1) rotate(-8deg)}}
@media (prefers-reduced-motion: reduce){.today-stamp{animation:none}}
`

/** A CSS-only "new country" stamp. The caller skips it under reduced motion. */
export default function PassportStamp({ code, city }) {
  const { t } = useTranslation('today')
  return (
    <div
      data-tid="today-stamp"
      role="img"
      aria-label={t('stamp', { code })}
      className="today-stamp inline-flex flex-col items-center rounded-md border-4 border-double border-rose-700 px-4 py-2 -rotate-6 text-rose-700"
    >
      <style>{CSS}</style>
      <span className="text-xs font-bold uppercase tracking-widest">{t('stampTitle')}</span>
      <span className="text-2xl font-extrabold">{code}</span>
      {city && <span className="text-xs">{city}</span>}
    </div>
  )
}
