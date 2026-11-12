import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { discoverDestinations } from '../../services/api'

const same = (a, b) => String(a || '').trim().toLowerCase() === String(b || '').trim().toLowerCase()

function inDays(n) {
  const d = new Date(Date.now() + n * 86400000)
  return d.toISOString().slice(0, 10)
}

/** "Where next?": asks the discovery agent only when tapped. */
export default function WhereNext({ trip, onUse }) {
  const { t } = useTranslation('recap')
  const [state, setState] = useState({ status: 'idle', items: [] })
  const current = [trip?.destination, ...(trip?.destinations || [])]
  const mounted = useRef(true)
  useEffect(() => { mounted.current = true; return () => { mounted.current = false } }, [])

  const load = async () => {
    onUse?.()
    const sd = trip?.search_data || {}
    // Discovery needs a home airport; the trip's destination is no substitute.
    const origin = sd.origin || trip?.origin
    if (!origin) { setState({ status: 'error', items: [], reason: 'origin' }); return }
    setState({ status: 'loading', items: [] })
    try {
      const res = await discoverDestinations({
        origin,
        nationality: sd.nationality || '',
        // discover requires a date; a month and a half out is a neutral placeholder
        departure_date: inDays(45),
        return_date: null,
        budget_usd: trip?.budget_usd ?? sd.budget_usd ?? null,
        interests: sd.interests || [],
        adults: Math.max(1, trip?.num_travelers || 1),
      })
      const items = (res?.destinations || []).filter((d) => !current.some((c) => same(c, d.city))).slice(0, 5)
      if (mounted.current) setState({ status: 'done', items })
    } catch {
      if (mounted.current) setState({ status: 'error', items: [] })
    }
  }

  return (
    <section className="rounded-xl border border-gray-200 bg-white p-4" data-tid="recap.where-next">
      <h3 className="font-semibold text-gray-900">{t('whereNext.title')}</h3>
      {state.status !== 'done' && (
        <button type="button" onClick={load} disabled={state.status === 'loading'} data-tid="recap.where-next-go"
          className="mt-2 min-h-[44px] rounded-lg bg-teal-700 px-4 text-sm font-medium text-white hover:bg-teal-800 disabled:opacity-60">
          {state.status === 'loading' ? t('whereNext.loading') : state.status === 'error' ? t('whereNext.retry') : t('whereNext.cta')}
        </button>
      )}
      {state.status === 'error' && <p className="mt-2 text-sm text-red-700" role="alert">{state.reason === 'origin' ? t('whereNext.needOrigin') : t('whereNext.failed')}</p>}
      {state.status === 'done' && state.items.length === 0 && (
        <p className="mt-2 text-sm text-gray-700">{t('whereNext.none')}</p>
      )}
      {state.items.length > 0 && (
        <ul className="mt-2 space-y-2" data-tid="recap.where-next-list">
          {state.items.map((d, i) => (
            <li key={`${d.city}-${i}`}>
              <Link to="/explore" state={{ prefill: { destination: `${d.city}, ${d.country}` } }}
                data-tid={`recap.where-next-item-${i}`}
                className="flex min-h-[44px] flex-col justify-center rounded-lg border border-gray-200 px-3 py-2 hover:bg-gray-50">
                <span className="font-medium text-gray-900">{d.city}, {d.country}</span>
                {d.tagline || d.reason ? <span className="text-xs text-gray-600">{d.tagline || d.reason}</span> : null}
              </Link>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
