import { useTranslation } from 'react-i18next'
import { ExternalLink, Landmark, CalendarDays, AlertTriangle } from 'lucide-react'
import { useClientConfig, featureOn } from '../hooks/useClientConfig'
import { fmtDate } from '../i18n/format'

/**
 * Official facts from the Voyager crawler (docs/Crawler-Data.md), shown with
 * their source, link and "as of" date wherever they appear. Every piece is
 * hidden unless /api/config reports `features.crawler_data` (an older or
 * flag-off backend never sends these fields anyway) and the section carries
 * the data. Share-alike facts (Wikipedia, OpenHolidays) are rendered on their
 * own, with their attribution, never mixed into the AI's fields.
 */

const LINK = { target: '_blank', rel: 'noopener noreferrer nofollow' }
const safeUrl = (u) => (typeof u === 'string' && /^https?:\/\//i.test(u) ? u : null)
const day = (d) => (typeof d === 'string' && /^\d{4}-\d{2}-\d{2}/.test(d)
  ? fmtDate(`${d.slice(0, 10)}T12:00:00`, { year: 'numeric', month: 'short', day: 'numeric' })
  : '')

export function useOfficialData() {
  const { config } = useClientConfig()
  return featureOn(config, 'crawler_data')
}

/** "Source: <name> · as of <date>" with the licence attribution under it. */
export function SourceLine({ source, className = '' }) {
  const { t } = useTranslation('results')
  if (!source || typeof source !== 'object') return null
  const name = source.name || source.source_id
  const url = safeUrl(source.url)
  const asOf = day(source.as_of)
  return (
    <p className={`text-[11px] text-gray-500 leading-snug ${className}`} data-testid="official-source">
      {url
        ? <a href={url} {...LINK} data-tid="results.official.source" className="inline-flex items-center gap-0.5 text-teal-700 hover:underline">{t('official.source', { name })}<ExternalLink size={9} /></a>
        : <span>{t('official.source', { name })}</span>}
      {asOf && <span> · {t('official.asOf', { date: asOf })}</span>}
      {source.via && <span> · {t('official.via', { currency: source.via })}</span>}
      {source.attribution && (
        <span className="block text-gray-400">
          {safeUrl(source.licence_url)
            ? <a href={source.licence_url} {...LINK} className="hover:underline">{source.attribution}</a>
            : source.attribution}
        </span>
      )}
      {source.conflict && (
        <span className="block text-amber-700"><AlertTriangle size={10} className="inline mr-0.5" />{t('official.disagree')}</span>
      )}
    </p>
  )
}

/** Under one exchange-rate card. */
export function RateSource({ rate }) {
  const on = useOfficialData()
  if (!on || !rate?.rate_source) return null
  return <SourceLine source={rate.rate_source} className="mt-1" />
}

/** Extra blocks of one emergency card (flat card or one `cities[]` entry). */
export function EmergencyOfficial({ card }) {
  const { t } = useTranslation('results')
  const on = useOfficialData()
  if (!on || !card) return null
  const ref = card.official_numbers
  const embassies = Array.isArray(card.embassies) ? card.embassies : []
  const others = embassies.filter(e => e && e.name !== card.embassy?.name)
  const medical = Array.isArray(card.medical_facilities) ? card.medical_facilities : []
  if (!card.emergency_numbers_source && !ref && !embassies.length && !medical.length) return null
  const services = ['police', 'ambulance', 'fire', 'tourist_police']
  const labels = { police: t('emergency.police'), ambulance: t('emergency.ambulance'), fire: t('emergency.fire'), tourist_police: t('emergency.touristPolice') }
  return (
    <div className="space-y-3" data-testid="emergency-official">
      {card.emergency_numbers_source && <SourceLine source={card.emergency_numbers_source} />}
      {ref?.numbers && (
        <div className="border border-gray-200 rounded-lg p-3 bg-gray-50">
          <p className="text-xs font-semibold text-gray-700 mb-1">{t('official.referenceNumbers')}</p>
          <p className="text-xs text-gray-700">
            {services.filter(s => ref.numbers[s]).map(s => `${labels[s]}: ${ref.numbers[s]}`).join(' · ')}
          </p>
          <SourceLine source={ref.source} className="mt-1" />
        </div>
      )}
      {card.embassy?.verified && card.embassy.source && (
        <div>
          <p className="text-[11px] font-semibold text-emerald-700 flex items-center gap-1"><Landmark size={11} />{t('official.officialContact')}</p>
          <SourceLine source={card.embassy.source} />
        </div>
      )}
      {others.length > 0 && (
        <div>
          <p className="text-xs font-semibold text-gray-700 mb-1">{t('official.otherOffices')}</p>
          <div className="space-y-1.5">
            {others.map((e, i) => (
              <div key={i} className="bg-white border border-gray-200 rounded-lg p-2.5">
                <p className="text-xs font-medium text-gray-800">{e.name}</p>
                {e.address && <p className="text-xs text-gray-600">{e.address}</p>}
                {e.phone && <p className="text-xs text-gray-600">📞 {e.phone}</p>}
                <SourceLine source={e.source} />
              </div>
            ))}
          </div>
        </div>
      )}
      {medical.length > 0 && (
        <div>
          <p className="text-sm font-semibold text-gray-700 mb-1">🏥 {t('official.medicalTitle')}</p>
          {card.medical_in_city === false && <p className="text-xs text-gray-500 mb-1">{t('official.medicalElsewhere')}</p>}
          <div className="space-y-1.5">
            {medical.map((m, i) => (
              <div key={i} className="bg-white border border-gray-200 rounded-lg p-2.5">
                <p className="text-sm font-medium text-gray-800">{m.name}{m.city ? <span className="text-xs text-gray-500"> · {m.city}</span> : null}</p>
                <p className="text-xs text-gray-600">{[m.phone && `📞 ${m.phone}`, m.address].filter(Boolean).join(' · ')}</p>
                {m.notes && <p className="text-xs text-gray-500 italic">{m.notes}</p>}
              </div>
            ))}
          </div>
          {medical[0]?.list_updated && <p className="text-[11px] text-gray-500 mt-1">{t('official.listUpdated', { date: day(medical[0].list_updated) })}</p>}
          <SourceLine source={medical[0]?.source} />
        </div>
      )}
    </div>
  )
}

/** "Phone number not verified" in place of a phone the AI guessed. */
export function PhoneUnverified() {
  const { t } = useTranslation('results')
  return <span className="text-amber-700" data-testid="phone-unverified">{t('official.phoneUnverified')}</span>
}

/** Official entry rules, travel advice and the Wikipedia cross-check. */
export function VisaOfficial({ entries }) {
  const { t } = useTranslation('results')
  const on = useOfficialData()
  if (!on || !Array.isArray(entries) || !entries.length) return null
  const multi = entries.length > 1
  return (
    <div className="space-y-3" data-testid="visa-official">
      {entries.map((e, i) => (
        <div key={i} className="border border-emerald-200 bg-emerald-50/50 rounded-xl p-3 space-y-2.5">
          <h3 className="text-sm font-bold text-emerald-800 flex items-center gap-1.5">
            <Landmark size={14} />{multi ? t('official.entryFor', { country: e.country }) : t('official.entryTitle')}
          </h3>
          {(e.rules || []).map((r, j) => (
            <div key={j} className="space-y-1">
              <p className="text-sm text-gray-800">
                <span className="font-semibold">{String(r.visa_type || '').replace(/_/g, ' ').toUpperCase()}</span>
                {r.max_stay_days ? <span> · {t('visa.days', { count: r.max_stay_days })}</span> : null}
                {r.stay_period_rule ? <span className="text-gray-600"> · {r.stay_period_rule}</span> : null}
                {r.fee ? <span className="text-gray-600"> · {t('visa.fee')} {r.fee}</span> : null}
              </p>
              {r.passport_validity_months ? <p className="text-xs text-gray-600">{t('official.passportValidity', { months: r.passport_validity_months })}</p> : null}
              {r.requirements?.length > 0 && (
                <ul className="list-disc ml-5 text-xs text-gray-700 space-y-0.5">{r.requirements.map((x, k) => <li key={k}>{x}</li>)}</ul>
              )}
              {r.notes && <p className="text-xs text-gray-600">{r.notes}</p>}
              {safeUrl(r.application_url) && (
                <a href={r.application_url} {...LINK} data-tid="results.official.visa-apply" className="inline-flex items-center gap-1 text-xs text-orange-600 hover:underline">
                  <ExternalLink size={10} />{t('official.apply')}
                </a>
              )}
              <SourceLine source={r.source} />
            </div>
          ))}
          {(e.advisories || []).length > 0 && (
            <div className="space-y-1.5">
              <p className="text-xs font-semibold text-gray-700 uppercase tracking-wide">{t('official.advice')}</p>
              {e.advisories.map((a, j) => (
                <div key={j} className="text-xs text-gray-700">
                  <p><span className="font-medium">{a.issuer}</span>{a.level_label ? `: ${a.level_label}` : ''}
                    {a.level != null && a.level_max ? <span className="text-gray-500"> ({t('official.level', { level: a.level, max: a.level_max })})</span> : null}</p>
                  {a.summary && <p className="text-gray-600">{a.summary}</p>}
                  <SourceLine source={a.source} />
                </div>
              ))}
            </div>
          )}
          {e.cross_check && (
            <div className="border-t border-emerald-100 pt-2">
              <p className="text-[11px] font-semibold text-gray-500">{t('official.crossCheck')}</p>
              <p className="text-xs text-gray-600">
                {String(e.cross_check.requirement || '').replace(/_/g, ' ')}
                {e.cross_check.allowed_stay_text ? ` · ${e.cross_check.allowed_stay_text}` : ''}
                {e.cross_check.agrees === true && <span className="text-emerald-700"> · {t('official.crossAgrees')}</span>}
                {e.cross_check.agrees === false && <span className="text-amber-700"> · {t('official.crossDiffers')}</span>}
              </p>
              <SourceLine source={e.cross_check.source} />
            </div>
          )}
        </div>
      ))}
    </div>
  )
}

/** Public holidays during the trip (events section and itinerary). */
export function HolidayNotice({ holidays, className = '' }) {
  const { t } = useTranslation('results')
  const on = useOfficialData()
  if (!on || !Array.isArray(holidays) || !holidays.length) return null
  const sources = []
  for (const h of holidays) {
    const s = h?.source
    if (s && !sources.some(x => x.source_id === s.source_id && x.url === s.url)) sources.push(s)
  }
  return (
    <div className={`bg-sky-50 border border-sky-200 rounded-xl p-3 space-y-2 ${className}`} data-testid="holiday-notice">
      <p className="text-sm font-semibold text-sky-900 flex items-center gap-1.5"><CalendarDays size={14} />{t('official.holidaysTitle')}</p>
      <div className="flex flex-wrap gap-1.5">
        {holidays.map((h, i) => (
          <span key={i} className="px-2 py-0.5 rounded-full bg-white border border-sky-200 text-xs text-sky-900">
            {day(h.start_date)}{h.end_date && h.end_date !== h.start_date ? `–${day(h.end_date)}` : ''} · {h.name}
            {!h.nationwide && <span className="text-sky-600"> ({t('official.regional')}{h.regions?.length ? `: ${h.regions.slice(0, 3).join(', ')}` : ''})</span>}
          </span>
        ))}
      </div>
      <p className="text-xs text-sky-800">{t('official.holidaysNote')}</p>
      {sources.map((s, i) => <SourceLine key={i} source={s} />)}
    </div>
  )
}

/** One line in the pricing banner: a cached fare, never called live. */
export function TypicalFares({ fares }) {
  const { t } = useTranslation('results')
  const on = useOfficialData()
  if (!on || !fares || typeof fares.price !== 'number') return null
  const price = `${Math.round(fares.price)} ${fares.currency || ''}`.trim()
  return (
    <div className="mt-2 border-t border-gray-200 pt-2" data-testid="typical-fares">
      <p className="text-xs text-gray-600">{t('official.typicalFare', { month: fares.month, price })}</p>
      <SourceLine source={fares.source} />
    </div>
  )
}
