import { useTranslation } from 'react-i18next'

const CONTINENTS = ['AF', 'AN', 'AS', 'EU', 'NA', 'OC', 'SA']

// ISO alpha-2 -> flag emoji (two regional indicator symbols).
export function flagEmoji(code) {
  const c = String(code || '').toUpperCase()
  if (!/^[A-Z]{2}$/.test(c)) return ''
  return String.fromCodePoint(...[...c].map((ch) => 0x1f1e6 + ch.charCodeAt(0) - 65))
}

function countryName(code, fallback, lang) {
  try {
    const name = new Intl.DisplayNames([lang], { type: 'region' }).of(String(code).toUpperCase())
    if (name && name !== String(code).toUpperCase()) return name
  } catch { /* unsupported locale or code */ }
  return fallback || code
}

// Countries the traveller has been to (from GET /trips/stats), with continents.
export default function CountriesVisited({ countries = [], continents = [], goal = null }) {
  const { t, i18n } = useTranslation('playYou')
  const lang = i18n.resolvedLanguage || i18n.language || 'en'
  const count = countries.length
  return (
    <section className="rounded-2xl bg-white p-6 shadow" aria-labelledby="countries-title" data-tid="play.countries">
      <h2 id="countries-title" className="mb-1 text-lg font-semibold text-slate-800">{t('countries.title')}</h2>
      <p className="mb-4 text-sm text-slate-600" data-tid="play.countries.count">
        {goal ? t('countries.countOfGoal', { count, goal }) : t('countries.count', { count })}
      </p>
      {count === 0 ? (
        <p className="text-sm text-slate-500" data-tid="play.countries.empty">{t('countries.empty')}</p>
      ) : (
        <ul className="grid grid-cols-1 gap-2 sm:grid-cols-2" data-tid="play.countries.list">
          {countries.map((c) => (
            <li key={c.code} data-tid={`play.country.${c.code}`}
              className="flex min-h-[44px] items-center gap-3 rounded-lg border border-slate-200 px-3 py-2 text-sm text-slate-800">
              <span aria-hidden="true" className="text-2xl">{flagEmoji(c.code)}</span>
              <span>{countryName(c.code, c.name, lang)}</span>
            </li>
          ))}
        </ul>
      )}
      {continents.length > 0 && (
        <div className="mt-4" data-tid="play.continents">
          <h3 className="mb-2 text-sm font-semibold text-slate-700">{t('continents.title', { count: continents.length })}</h3>
          <ul className="flex flex-wrap gap-2">
            {continents.filter((c) => CONTINENTS.includes(c)).map((c) => (
              <li key={c} data-tid={`play.continent.${c}`}
                className="rounded-full bg-teal-50 px-3 py-1 text-xs font-medium text-teal-800 dark:bg-teal-900 dark:text-teal-100">
                {t(`continents.${c}`)}
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  )
}
