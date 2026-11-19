import { useEffect, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Leaf, Info, X, TrainFront } from 'lucide-react'
import { fetchTripCarbon } from '../services/api'
import { useClientConfig, featureOn } from '../hooks/useClientConfig'
import { fmtNumber } from '../i18n/format'
import {
  DIETS, CATEGORY_KEYS, carbonRequestFromResults, carbonRequestFromSelections, pctLabel,
} from '../utils/carbon'

// Literal class names so Tailwind keeps them
const COLORS = {
  flights: 'bg-sky-500',
  stays: 'bg-purple-500',
  ground: 'bg-amber-500',
  food: 'bg-green-500',
  activities: 'bg-pink-500',
}
const METHOD_STYLE = {
  measured_tim: 'bg-emerald-50 text-emerald-700 border-emerald-200',
  factor: 'bg-sky-50 text-sky-700 border-sky-200',
  estimate: 'bg-amber-50 text-amber-700 border-amber-200',
}
const DIET_KEY = 'tp_carbon_diet'

function readDiet() {
  try {
    const d = localStorage.getItem(DIET_KEY)
    return DIETS.includes(d) ? d : 'mixed'
  } catch { return 'mixed' }
}
function writeDiet(d) {
  try { localStorage.setItem(DIET_KEY, d) } catch { /* private mode */ }
}

const kg0 = (n) => fmtNumber(Math.round(n))
const kg1 = (n) => fmtNumber(n, { maximumFractionDigits: n < 10 ? 1 : 0 })

/**
 * The trip's carbon footprint, worked out by POST /api/carbon/trip (pure
 * computation on the server; docs/Carbon-Footprint.md). `mode="results"`
 * sends the search result summary, `mode="plan"` the My Plan selections.
 * Hidden unless /api/config reports `features.carbon` (an older backend
 * never shows it), and hidden again if the endpoint answers 404.
 */
export default function CarbonFootprint({ mode = 'results', searchData, results, selections, itinerary, compact = false }) {
  const { t } = useTranslation('results')
  const { config } = useClientConfig()
  const on = featureOn(config, 'carbon')
  const [diet, setDiet] = useState(readDiet)
  const [state, setState] = useState({ status: 'idle' })
  const [open, setOpen] = useState(false)
  const seq = useRef(0)

  const body = useMemo(() => (
    mode === 'plan'
      ? carbonRequestFromSelections({ searchData, selections, itinerary, diet })
      : carbonRequestFromResults({ searchData, results, diet })
  ), [mode, searchData, results, selections, itinerary, diet])
  const bodyKey = useMemo(() => JSON.stringify(body), [body])

  useEffect(() => {
    if (!on) return undefined
    const mine = ++seq.current
    setState((s) => (s.status === 'ok' ? { ...s, refreshing: true } : { status: 'loading' }))
    const timer = setTimeout(async () => {
      try {
        const data = await fetchTripCarbon(JSON.parse(bodyKey))
        if (mine === seq.current) setState({ status: 'ok', data })
      } catch (err) {
        if (mine !== seq.current) return
        setState({ status: err?.response?.status === 404 ? 'gone' : 'error' })
      }
    }, 350)
    return () => clearTimeout(timer)
  }, [on, bodyKey])

  useEffect(() => {
    if (!open) return undefined
    const onKey = (e) => { if (e.key === 'Escape') setOpen(false) }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [open])

  if (!on || state.status === 'gone' || state.status === 'idle') return null

  const changeDiet = (d) => { setDiet(d); writeDiet(d) }
  const data = state.data
  const cats = (data?.categories || []).filter((c) => CATEGORY_KEYS.includes(c.key) && c.kg > 0)
  const total = data?.total_kg || 0
  const hint = (data?.lower_carbon || []).filter((h) => h.saving_kg > 0).sort((a, b) => b.saving_kg - a.saving_kg)[0]
  const cmp = data?.comparisons || {}
  const lineLabel = (ln) => t(`carbon.line.${ln.kind}`, {
    ...ln.params,
    mode: ln.params?.mode ? t(`carbon.mode.${ln.params.mode}`, { defaultValue: ln.params.mode }) : undefined,
    diet: ln.params?.diet ? t(`carbon.diet.${ln.params.diet}`) : undefined,
    defaultValue: ln.label,
  })
  const assumption = (a) => t(`carbon.assume.${a.code}`, {
    ...a.params,
    diet: a.params?.diet ? t(`carbon.diet.${a.params.diet}`) : undefined,
    cabin: a.params?.cabin ? t(`carbon.cabin.${a.params.cabin}`) : undefined,
    defaultValue: a.text,
  })

  return (
    <section
      data-testid="carbon-footprint"
      aria-labelledby={`carbon-heading-${mode}`}
      className={compact ? 'border border-gray-200 rounded-xl p-3' : 'bg-white rounded-2xl border border-gray-200 shadow-sm p-4'}
    >
      <header className="flex items-center justify-between gap-2">
        <h3 id={`carbon-heading-${mode}`} className={compact
          ? 'text-xs font-semibold text-gray-500 uppercase tracking-wide flex items-center gap-1.5'
          : 'font-semibold text-gray-800 text-sm flex items-center gap-1.5'}>
          <Leaf size={compact ? 11 : 14} className="text-emerald-600" aria-hidden="true" /> {t('carbon.title')}
        </h3>
        {state.status === 'ok' && (
          <button type="button" data-tid="carbon.how" aria-expanded={open} aria-controls={`carbon-how-${mode}`}
            onClick={() => setOpen((v) => !v)}
            className="text-xs text-teal-700 hover:text-teal-900 inline-flex items-center gap-1">
            <Info size={12} aria-hidden="true" /> {t('carbon.how')}
          </button>
        )}
      </header>

      {state.status === 'loading' && <p className="mt-2 text-xs text-gray-400" role="status">{t('carbon.loading')}</p>}
      {state.status === 'error' && <p className="mt-2 text-xs text-gray-500">{t('carbon.error')}</p>}

      {state.status === 'ok' && data && (
        <div className={state.refreshing ? 'opacity-70 transition-opacity' : undefined}>
          <p className="mt-2">
            <span data-testid="carbon-total" className={`font-bold text-gray-900 tabular-nums ${compact ? 'text-base' : 'text-xl'}`}>
              {t('carbon.total', { kg: kg0(total) })}
            </span>
            {data.travellers > 1 && (
              <span className="ml-2 text-xs text-gray-500">{t('carbon.perPerson', { kg: kg0(data.per_person_kg) })}</span>
            )}
          </p>

          {total > 0 && (
            <>
              <div className="mt-2 flex h-2.5 rounded-full overflow-hidden bg-gray-100 gap-px" role="img"
                aria-label={cats.map((c) => `${t(`carbon.cat.${c.key}`)} ${pctLabel(c.share)}`).join(', ')}>
                {cats.map((c) => (
                  <div key={c.key} data-testid={`carbon-bar-${c.key}`} className={COLORS[c.key]} style={{ width: `${c.share * 100}%` }} />
                ))}
              </div>
              <ul className="mt-2 grid grid-cols-1 sm:grid-cols-2 gap-x-4 gap-y-1">
                {cats.map((c) => (
                  <li key={c.key} className="flex items-center gap-2 text-xs">
                    <span className={`w-2 h-2 rounded-full shrink-0 ${COLORS[c.key]}`} aria-hidden="true" />
                    <span className="flex-1 text-gray-600">{t(`carbon.cat.${c.key}`)}</span>
                    <span className="tabular-nums text-gray-800 font-medium">{t('carbon.kg', { kg: kg0(c.kg) })}</span>
                    <span className="tabular-nums text-gray-400 w-9 text-right">{pctLabel(c.share)}</span>
                  </li>
                ))}
              </ul>
            </>
          )}

          {total > 0 && (
            <ul className="mt-2 text-xs text-gray-500 space-y-0.5">
              {cmp.car_km > 0 && <li>{t('carbon.carKm', { km: fmtNumber(cmp.car_km) })}</li>}
              {cmp.budget_share > 0 && (
                <li>{t('carbon.budget', { pct: pctLabel(cmp.budget_share), tonnes: fmtNumber((cmp.annual_budget_kg || 2000) / 1000) })}</li>
              )}
            </ul>
          )}

          {hint && (
            <p data-testid="carbon-rail-hint" className="mt-2 flex items-start gap-1.5 text-xs text-emerald-800 bg-emerald-50 border border-emerald-200 rounded-lg px-2 py-1.5">
              <TrainFront size={13} className="mt-px shrink-0" aria-hidden="true" />
              <span>{t('carbon.railHint', { route: hint.route, km: fmtNumber(hint.rail_km), kg: kg0(hint.saving_kg) })}</span>
            </p>
          )}

          <label className="mt-2 flex items-center gap-2 text-xs text-gray-600">
            {t('carbon.diet.label')}
            <select data-tid="carbon.diet" value={diet} onChange={(e) => changeDiet(e.target.value)}
              className="border border-gray-200 rounded-md px-1.5 py-0.5 text-xs bg-white">
              {DIETS.map((d) => <option key={d} value={d}>{t(`carbon.diet.${d}`)}</option>)}
            </select>
          </label>

          {open && (
            <div id={`carbon-how-${mode}`} role="region" aria-label={t('carbon.how')}
              className="mt-3 border border-gray-200 rounded-xl p-3 bg-gray-50 text-xs text-gray-700 space-y-3">
              <div className="flex items-start justify-between gap-2">
                <p>{t('carbon.howIntro')}</p>
                <button type="button" data-tid="carbon.how-close" onClick={() => setOpen(false)}
                  aria-label={t('carbon.close')} className="text-gray-400 hover:text-gray-700"><X size={13} /></button>
              </div>
              <div>
                <h4 className="font-semibold text-gray-800 mb-1">{t('carbon.linesTitle')}</h4>
                <ul className="space-y-1">
                  {data.lines.map((ln, i) => (
                    <li key={i} className="flex items-start gap-2">
                      <span className={`shrink-0 px-1.5 rounded border text-[10px] font-medium ${METHOD_STYLE[ln.method] || ''}`}>
                        {t(`carbon.method.${ln.method}`)}
                      </span>
                      <span className="flex-1">{lineLabel(ln)}</span>
                      <span className="tabular-nums font-medium">{t('carbon.kg', { kg: kg1(ln.kg) })}</span>
                    </li>
                  ))}
                </ul>
              </div>
              {data.assumptions?.length > 0 && (
                <div>
                  <h4 className="font-semibold text-gray-800 mb-1">{t('carbon.assumptionsTitle')}</h4>
                  <ul className="list-disc ml-4 space-y-0.5">
                    {data.assumptions.map((a, i) => <li key={i}>{assumption(a)}</li>)}
                  </ul>
                </div>
              )}
              <div>
                <h4 className="font-semibold text-gray-800 mb-1">{t('carbon.sourcesTitle')}</h4>
                <ul className="space-y-1">
                  {(data.sources || []).map((s) => (
                    <li key={s.id}>
                      {s.url ? (
                        <a href={s.url} target="_blank" rel="noopener noreferrer" className="text-teal-700 underline">{s.name}</a>
                      ) : s.name}
                      {s.publisher && <span className="text-gray-500"> · {s.publisher}</span>}
                      {s.licence && <span className="text-gray-500"> · {s.licence}</span>}
                      {s.attribution && <div data-testid={`carbon-attribution-${s.id}`} className="text-gray-500">{s.attribution}</div>}
                    </li>
                  ))}
                </ul>
              </div>
            </div>
          )}
        </div>
      )}
    </section>
  )
}
