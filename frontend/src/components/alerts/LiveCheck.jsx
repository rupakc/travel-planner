import { useCallback, useEffect, useRef, useState } from 'react'
import { Globe, Loader2, X } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { formatPrice } from '../../utils/priceWatch'
import { googleSearchUrl, liveErrorMessage, usableSources } from '../../utils/liveResults'

const quiet = 'inline-flex items-center gap-1.5 rounded-full px-3 py-1.5 text-xs font-medium text-slate-600 hover:bg-slate-100 hover:text-slate-800 disabled:opacity-50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-sky-500'

/**
 * State for one card's "Search the web now". `run` performs the request (it
 * resolves to the API's answer). The answer stays in this hook's state only:
 * it never touches the watch, its price history or any storage.
 */
export function useLiveCheck(run) {
  const [state, setState] = useState({ status: 'idle', result: null, error: null })
  const seq = useRef(0)
  useEffect(() => () => { seq.current += 1 }, [])

  const start = useCallback(async () => {
    const id = ++seq.current
    setState({ status: 'loading', result: null, error: null })
    try {
      const result = await run()
      if (seq.current === id) setState({ status: 'done', result, error: null })
    } catch (err) {
      if (seq.current === id) setState({ status: 'error', result: null, error: liveErrorMessage(err, 'live') })
    }
  }, [run])

  const dismiss = useCallback(() => {
    seq.current += 1
    setState({ status: 'idle', result: null, error: null })
  }, [])

  return { ...state, start, dismiss }
}

/** The card's action-row button. */
export function LiveCheckButton({ live, buttonRef }) {
  const { t } = useTranslation('alerts')
  const loading = live.status === 'loading'
  return (
    <button type="button" data-tid="alerts.live-check" ref={buttonRef} onClick={live.start} disabled={loading} className={quiet}>
      {loading ? <Loader2 size={12} className="animate-spin" aria-hidden="true" /> : <Globe size={12} aria-hidden="true" />}
      {loading ? t('live.searching') : t('live.searchNow')}
    </button>
  )
}

function quoteAmount(q) {
  if (typeof q?.amount !== 'number' || !Number.isFinite(q.amount)) return ''
  return q.currency ? formatPrice(q.amount, q.currency, { cents: true }) : String(q.amount)
}

/**
 * The inline answer under a watch card: summary (as returned), quotes with
 * their sources, what was searched for, all sources and the disclaimer.
 * Live region so the outcome is read out; dismissible.
 */
export function LiveCheckPanel({ live, onDismissed, title, buttonRef = null }) {
  const { t } = useTranslation('alerts')
  const headingRef = useRef(null)
  useEffect(() => {
    if (live.status !== 'done' && live.status !== 'error') return
    // Only take focus if the user is still where they started (the card's
    // button, or nowhere because the disabled button dropped it)
    const active = document.activeElement
    if (!active || active === document.body || active === buttonRef?.current) headingRef.current?.focus()
  }, [live.status, buttonRef])

  const close = () => { live.dismiss(); onDismissed?.() }
  const r = live.result
  const sources = live.status === 'done' ? usableSources(r?.sources) : []
  const byIndex = new Map(sources.map(s => [s.index, s]))
  const quotes = (Array.isArray(r?.quotes) ? r.quotes : []).filter(q => q && (q.label || quoteAmount(q)))
  const queries = (Array.isArray(r?.searched_for) ? r.searched_for : []).filter(q => typeof q === 'string' && q.trim())

  return (
    <div data-testid="live-check-region">
      {/* One short announcement; the panel itself isn't a live region (errors use role=alert) */}
      <p className="sr-only" role="status" data-testid="live-check-status">
        {live.status === 'loading' ? t('live.searching') : live.status === 'done' ? t('live.ready') : ''}
      </p>
      {live.status === 'loading' && (
        <p className="mt-3 flex items-center gap-2 text-sm text-slate-500" data-testid="live-check-loading">
          <Loader2 size={14} className="animate-spin" aria-hidden="true" /> {title ? t('live.searchingFor', { title }) : t('live.searchingThis')}
        </p>
      )}

      {live.status === 'error' && live.error && (
        <div role="alert" className="mt-3 flex flex-wrap items-start justify-between gap-2 rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900">
          <p ref={headingRef} tabIndex={-1} className="min-w-0 flex-1 focus:outline-none">{live.error.text}</p>
          <span className="flex items-center gap-1">
            {live.error.retry && (
              <button type="button" data-tid="alerts.live-retry" onClick={live.start}
                className="rounded-full border border-amber-300 bg-white px-3 py-1 text-xs font-semibold hover:bg-amber-100">{t('ui.tryAgain')}</button>
            )}
            <button type="button" data-tid="alerts.live-error-dismiss" onClick={close} aria-label={t('ui.dismiss')} className="rounded-full p-1 hover:bg-amber-100">
              <X size={14} aria-hidden="true" />
            </button>
          </span>
        </div>
      )}

      {live.status === 'done' && r && (
        <section aria-label={t('live.resultLabel')} data-testid="live-check-panel"
          className="mt-3 rounded-xl border border-sky-100 bg-sky-50/60 p-4 text-sm text-slate-700">
          <div className="flex items-start justify-between gap-2">
            <h4 ref={headingRef} tabIndex={-1} className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-sky-800 focus:outline-none">
              <Globe size={12} aria-hidden="true" /> {t('live.heading')}
            </h4>
            <button type="button" data-tid="alerts.live-dismiss" onClick={close} aria-label={t('live.dismissResult')}
              className="-mr-1 -mt-1 rounded-full p-1 text-slate-500 hover:bg-white hover:text-slate-700 focus-visible:outline focus-visible:outline-2 focus-visible:outline-sky-500">
              <X size={14} aria-hidden="true" />
            </button>
          </div>

          {r.summary && <p className="mt-2 whitespace-pre-line" data-testid="live-check-summary">{r.summary}</p>}

          {quotes.length > 0 && (
            <ul className="mt-3 space-y-1" aria-label={t('live.pricesFound')}>
              {quotes.map((q, i) => {
                const src = byIndex.get(q.source_index)
                return (
                  <li key={i} className="flex flex-wrap items-baseline gap-x-2">
                    <span className="font-semibold tabular-nums text-slate-900">{quoteAmount(q)}</span>
                    {q.label && <span>{q.label}</span>}
                    {src && (
                      <a href={src.uri} data-tid="alerts.live-quote-source" target="_blank" rel="noopener noreferrer"
                        className="text-xs text-sky-700 underline-offset-2 hover:underline">{src.title}</a>
                    )}
                  </li>
                )
              })}
            </ul>
          )}

          {queries.length > 0 && (
            <p className="mt-3 text-xs text-slate-500">
              {t('live.searchedFor')}{' '}
              {queries.map((q, i) => (
                <span key={i}>
                  {i > 0 && ', '}
                  <a href={googleSearchUrl(q)} data-tid="alerts.live-query" target="_blank" rel="noopener noreferrer" className="text-sky-700 underline-offset-2 hover:underline">{q}</a>
                </span>
              ))}
            </p>
          )}

          {sources.length > 0 && (
            <div className="mt-3">
              <h5 className="text-xs font-semibold text-slate-600">{t('live.sources')}</h5>
              <ul className="mt-1 space-y-0.5 text-xs">
                {sources.map(s => (
                  <li key={s.index}>
                    <a href={s.uri} data-tid="alerts.live-source" target="_blank" rel="noopener noreferrer" className="text-sky-700 underline-offset-2 hover:underline">{s.title}</a>
                  </li>
                ))}
              </ul>
            </div>
          )}

          <p className="mt-3 text-[11px] text-slate-500">{r.disclaimer || t('live.disclaimer')}</p>
        </section>
      )}
    </div>
  )
}
