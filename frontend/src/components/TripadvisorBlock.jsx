import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { ExternalLink, Loader2, RefreshCw } from 'lucide-react'
import { fetchTripadvisorAttractions } from '../services/api'
import { useClientConfig, featureOn } from '../hooks/useClientConfig'
import { fmtNumber } from '../i18n/format'

/**
 * Tripadvisor ratings for the top attractions around a destination, fetched
 * live only when the traveller asks (each lookup is billed). Tripadvisor's
 * terms shape this block:
 *  - its own clearly labelled card with the Tripadvisor logo, never merged
 *    into our places list, ranking, verification, package or itinerary;
 *  - every name and review count links back to Tripadvisor;
 *  - values are shown as returned and in Tripadvisor's order;
 *  - the answer lives in this component's state only: never saved to the
 *    plan, share links, offline pack, storage, telemetry or the AI.
 * Hidden unless /api/config reports `features.tripadvisor` (an older or
 * flag-off backend never shows it) and the user is signed in.
 */
const LINK = { target: '_blank', rel: 'noopener noreferrer nofollow' }

export default function TripadvisorBlock({ destinations = [], token }) {
  const { t } = useTranslation('results')
  const { config } = useClientConfig()
  const cities = [...new Set(destinations.filter(Boolean))]
  const [city, setCity] = useState(null)
  const [state, setState] = useState({ status: 'idle' })

  if (!token || !cities.length || !featureOn(config, 'tripadvisor')) return null

  const load = async (name) => {
    setCity(name)
    setState({ status: 'loading' })
    try {
      const data = await fetchTripadvisorAttractions(name, token)
      setState({ status: data?.status || 'empty', items: data?.items || [], attribution: data?.attribution })
    } catch {
      setState({ status: 'error' })
    }
  }

  const attribution = state.attribution || {}
  return (
    <section
      data-nosnippet=""
      data-testid="tripadvisor-block"
      aria-label={t('tripadvisor.title')}
      className="bg-white rounded-2xl border border-gray-200 shadow-sm p-4"
    >
      <header className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="font-semibold text-gray-800 text-sm">{t('tripadvisor.title')}</h3>
        {state.status !== 'idle' && state.status !== 'loading' && (
          <button type="button" data-tid="results.tripadvisor.hide"
            onClick={() => setState({ status: 'idle' })}
            className="text-xs text-gray-500 hover:text-gray-700">
            {t('tripadvisor.hide')}
          </button>
        )}
      </header>

      {state.status === 'idle' && (
        <div className="flex flex-wrap gap-2 mt-3">
          {cities.map((name) => (
            <button key={name} type="button" data-tid="results.tripadvisor.show"
              onClick={() => load(name)}
              className="px-3 py-1.5 rounded-full text-xs font-semibold border border-emerald-300 text-emerald-700 hover:bg-emerald-50">
              {cities.length > 1 ? t('tripadvisor.showFor', { city: name }) : t('tripadvisor.show')}
            </button>
          ))}
        </div>
      )}

      {state.status === 'loading' && (
        <p className="mt-3 text-sm text-gray-500 flex items-center gap-2" role="status">
          <Loader2 size={14} className="animate-spin" /> {t('tripadvisor.loading')}
        </p>
      )}

      {state.status === 'paused' && (
        <p className="mt-3 text-sm text-gray-500" data-testid="tripadvisor-paused">{t('tripadvisor.paused')}</p>
      )}

      {state.status === 'empty' && (
        <p className="mt-3 text-sm text-gray-500">{t('tripadvisor.empty')}</p>
      )}

      {state.status === 'error' && (
        <p className="mt-3 text-sm text-red-600 flex flex-wrap items-center gap-2">
          {t('tripadvisor.error')}
          <button type="button" data-tid="results.tripadvisor.retry" onClick={() => load(city)}
            className="text-xs font-semibold text-gray-700 flex items-center gap-1">
            <RefreshCw size={12} /> {t('tripadvisor.retry')}
          </button>
        </p>
      )}

      {state.status === 'ok' && (
        <div className="mt-3">
          <a href="https://www.tripadvisor.com/" {...LINK} data-tid="results.tripadvisor.logo"
            className="inline-flex items-center">
            {attribution.logo_url
              ? <img src={attribution.logo_url} alt={t('tripadvisor.logoAlt')} className="h-5 w-auto" />
              : <span className="font-semibold text-sm">{t('tripadvisor.logoAlt')}</span>}
          </a>
          <ol className="mt-3 divide-y divide-gray-100">
            {state.items.map((item) => (
              <li key={item.id ?? item.web_url} className="py-2 flex flex-col gap-0.5">
                <a href={item.web_url} {...LINK} data-tid="results.tripadvisor.name"
                  className="font-medium text-gray-900 hover:underline">
                  {item.name}
                </a>
                <div className="flex flex-wrap items-center gap-2 text-xs text-gray-600">
                  {item.rating_image_url && (
                    <img src={item.rating_image_url} alt={t('tripadvisor.ratingAlt', { rating: item.rating })} className="h-4 w-auto" />
                  )}
                  {item.rating != null && !item.rating_image_url && (
                    <span>{t('tripadvisor.ratingAlt', { rating: item.rating })}</span>
                  )}
                  {item.num_reviews != null && (
                    <a href={item.web_url} {...LINK} data-tid="results.tripadvisor.reviews" className="hover:underline">
                      {t('tripadvisor.reviews', { count: Number(item.num_reviews), n: fmtNumber(Number(item.num_reviews)) })}
                    </a>
                  )}
                  {item.ranking && <span>{item.ranking}</span>}
                  {item.category && <span className="text-gray-400">{item.category}</span>}
                  <ExternalLink size={10} className="text-gray-400" aria-hidden="true" />
                </div>
              </li>
            ))}
          </ol>
          <p className="mt-2 text-[11px] text-gray-400">{t('tripadvisor.note')}</p>
        </div>
      )}
    </section>
  )
}
