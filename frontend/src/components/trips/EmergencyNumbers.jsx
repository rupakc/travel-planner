import { useTranslation } from 'react-i18next'
import { fmtDate } from '../../i18n/format'

const telHref = (n) => `tel:${String(n).replace(/[^\d+*#]/g, '')}`
const isNum = (v) => (typeof v === 'string' || typeof v === 'number') && /\d/.test(String(v))

// Emergency numbers as large tel: links, labelled with where they came from.
export default function EmergencyNumbers({ emergency }) {
  const { t } = useTranslation('offlinePack')
  const cities = emergency?.cities || []
  if (!cities.length) return null
  const source = emergency.source === 'ai' && emergency.as_of
    ? t('emergency.checked', { date: fmtDate(emergency.as_of, { day: 'numeric', month: 'short', year: 'numeric' }) })
    : t('emergency.reference')
  return (
    <section data-tid="offlinePack.emergency" className="rounded-xl border border-red-200 bg-white p-4">
      <h3 className="text-sm font-semibold text-gray-700">{t('emergency.title')}</h3>
      <p data-tid="offlinePack.emergency.source" className="text-xs text-gray-600 mb-2">{source}</p>
      {cities.map((c, i) => (
        <div key={`${c.city}-${i}`} className="mb-3 last:mb-0">
          {cities.length > 1 && <p className="font-medium text-gray-800 mb-1">{c.city}</p>}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
            {Object.entries(c.emergency_numbers || {}).filter(([, v]) => isNum(v)).map(([k, v]) => (
              <a
                key={k}
                href={telHref(v)}
                data-tid={`offlinePack.emergency.call.${k}`}
                className="flex items-center justify-between min-h-[56px] rounded-lg bg-red-50 px-4 text-red-900"
              >
                <span className="text-sm">{t(`emergency.kinds.${k}`, { defaultValue: k.replace(/_/g, ' ') })}</span>
                <span className="text-2xl font-bold">{String(v)}</span>
              </a>
            ))}
          </div>
          {c.embassy?.name && (
            <p className="mt-2 text-sm text-gray-700">
              {t('emergency.embassy')}: {c.embassy.name}
              {c.embassy.phone && <> · <a className="underline inline-block min-h-[44px] leading-[44px]" href={telHref(c.embassy.phone)} data-tid="offlinePack.emergency.embassy">{c.embassy.phone}</a></>}
            </p>
          )}
          {(c.hospitals || []).filter((h) => h?.name).map((h) => (
            <p key={h.name} className="text-sm text-gray-700">
              {t('emergency.hospital')}: {h.name}
              {h.phone && <> · <a className="underline inline-block min-h-[44px] leading-[44px]" href={telHref(h.phone)} data-tid="offlinePack.emergency.hospital">{h.phone}</a></>}
            </p>
          ))}
        </div>
      ))}
    </section>
  )
}
