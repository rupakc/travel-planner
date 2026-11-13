import { useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { MAP_WIDTH, MAP_HEIGHT, decodeCountries, countryPath, visitedSet, regionName } from '../../utils/scratchMap'

// Loaded lazily (React.lazy in ScratchMap): the dataset is its own chunk.
export default function ScratchMapSvg({ countries = [] }) {
  const { t, i18n } = useTranslation('playYou')
  const lang = i18n.resolvedLanguage || i18n.language || 'en'
  const [shapes, setShapes] = useState(null)
  const [picked, setPicked] = useState(null)
  const visited = useMemo(() => visitedSet(countries), [countries])

  useEffect(() => {
    let live = true
    import('../../assets/worldCountries.json').then((m) => {
      if (live) setShapes(decodeCountries(m.default || m).map((c) => ({ code: c.code, d: countryPath(c.rings) })))
    }).catch(() => {})
    return () => { live = false }
  }, [])

  if (!shapes) return <p className="text-sm text-slate-500">{t('countries.mapLoading')}</p>
  return (
    <div data-tid="play.scratchmap">
      <svg viewBox={`0 0 ${MAP_WIDTH} ${MAP_HEIGHT}`} role="img"
        aria-label={t('countries.mapLabel', { count: visited.size })}
        className="h-auto w-full rounded-lg bg-slate-100">
        {shapes.map((s) => (
          <path key={s.code} d={s.d} data-tid={`play.map.${s.code}`}
            onClick={() => setPicked(s.code)} onMouseEnter={() => setPicked(s.code)}
            className={`${visited.has(s.code) ? 'fill-teal-500' : 'fill-slate-300'} stroke-white`}
            strokeWidth="0.6" vectorEffect="non-scaling-stroke" />
        ))}
      </svg>
      <p className="mt-2 min-h-[1.25rem] text-sm text-slate-600" aria-live="polite" data-tid="play.scratchmap.label">
        {picked ? `${regionName(picked, lang)}${visited.has(picked) ? ' ✓' : ''}` : t('countries.mapHint')}
      </p>
    </div>
  )
}
