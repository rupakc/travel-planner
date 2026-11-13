import { useEffect, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { MAP_WIDTH, MAP_HEIGHT, decodeCountries, countryPath, visitedSet, regionName } from '../../utils/scratchMap'

// Loaded lazily (React.lazy in ScratchMap): the dataset is its own chunk.
export default function ScratchMapSvg({ countries = [] }) {
  const { t, i18n } = useTranslation('playYou')
  const lang = i18n.resolvedLanguage || i18n.language || 'en'
  const [shapes, setShapes] = useState(null)
  const [picked, setPicked] = useState(null)
  const [active, setActive] = useState(null)
  const svgRef = useRef(null)
  const visited = useMemo(() => visitedSet(countries), [countries])

  useEffect(() => {
    let live = true
    import('../../assets/worldCountries.json').then((m) => {
      if (live) setShapes(decodeCountries(m.default || m).map((c) => ({ code: c.code, d: countryPath(c.rings) })))
    }).catch(() => {})
    return () => { live = false }
  }, [])

  const order = useMemo(() => (shapes || []).filter((s) => visited.has(s.code)).map((s) => s.code), [shapes, visited])
  const tabStop = order.includes(active) ? active : order[0]

  const move = (code, delta) => {
    const i = order.indexOf(code)
    const next = order[(i + delta + order.length) % order.length]
    setActive(next)
    setPicked(next)
    svgRef.current?.querySelector(`[data-tid="play.map.${next}"]`)?.focus()
  }

  const onKey = (e, code) => {
    if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setPicked(code) }
    else if (e.key === 'ArrowRight' || e.key === 'ArrowDown') { e.preventDefault(); move(code, 1) }
    else if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') { e.preventDefault(); move(code, -1) }
    else if (e.key === 'Home') { e.preventDefault(); move(order[order.length - 1], 1) }
    else if (e.key === 'End') { e.preventDefault(); move(order[0], -1) }
  }

  if (!shapes) return <p className="text-sm text-slate-500">{t('countries.mapLoading')}</p>
  return (
    <div data-tid="play.scratchmap">
      <svg ref={svgRef} viewBox={`0 0 ${MAP_WIDTH} ${MAP_HEIGHT}`} role="group"
        aria-label={t('countries.mapLabel', { count: visited.size })}
        aria-describedby="countries-visited-list"
        className="h-auto w-full rounded-lg bg-slate-100">
        {shapes.map((s) => {
          const seen = visited.has(s.code)
          const cls = `${seen ? 'fill-teal-500' : 'fill-slate-300'} stroke-white focus:outline-none focus-visible:stroke-sky-600 focus-visible:[stroke-width:2.5px]`
          return seen ? (
            <path key={s.code} d={s.d} data-tid={`play.map.${s.code}`}
              role="button" tabIndex={s.code === tabStop ? 0 : -1} aria-label={`${regionName(s.code, lang)} ✓`}
              onClick={() => { setActive(s.code); setPicked(s.code) }} onMouseEnter={() => setPicked(s.code)}
              onFocus={() => { setActive(s.code); setPicked(s.code) }}
              onKeyDown={(e) => onKey(e, s.code)}
              className={cls} strokeWidth="0.6" vectorEffect="non-scaling-stroke" />
          ) : (
            <path key={s.code} d={s.d} data-tid={`play.map.${s.code}`} aria-hidden="true"
              onClick={() => setPicked(s.code)} onMouseEnter={() => setPicked(s.code)}
              className={cls} strokeWidth="0.6" vectorEffect="non-scaling-stroke" />
          )
        })}
      </svg>
      <p className="mt-2 min-h-[1.25rem] text-sm text-slate-600" aria-live="polite" data-tid="play.scratchmap.label">
        {picked ? `${regionName(picked, lang)}${visited.has(picked) ? ' ✓' : ''}` : t('countries.mapHint')}
      </p>
    </div>
  )
}
