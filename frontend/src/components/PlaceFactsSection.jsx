import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Check, Plus, Sparkles } from 'lucide-react'
import { SourceLine } from './OfficialData'
import { langAttr, quotedValue } from '../utils/placeFactText'

/**
 * Place facts (docs/Place-Facts.md): five groups of facts about each
 * destination, its region and its country. Crawler facts show their source
 * (name, link, as-of, licence attribution); AI facts are labelled
 * "AI-suggested, not verified" and never carry a source or link. The crawler
 * writes no `fun` facts, so that group is AI-suggested. A crawler fact's
 * `lang` / `value_lang` (both optional) become `lang` attributes.
 *
 * The section is only rendered when the backend sent it (an older backend
 * never does), and it hides itself when there is nothing to show.
 */

export const FACT_TYPES = ['historical', 'fun', 'popular', 'unbelievable', 'little_known']

const isFact = (f) => f && typeof f === 'object' && typeof f.text === 'string' && f.text.trim()

export function placesWithFacts(data) {
  if (!data || typeof data !== 'object' || data.error || !Array.isArray(data.places)) return []
  return data.places
    .filter(p => p && typeof p === 'object' && p.groups && typeof p.groups === 'object')
    .map(p => ({
      ...p,
      groups: Object.fromEntries(FACT_TYPES.map(t => [t, (Array.isArray(p.groups[t]) ? p.groups[t] : []).filter(isFact)])),
    }))
    .filter(p => FACT_TYPES.some(t => p.groups[t].length))
}

export function hasPlaceFacts(data) {
  return placesWithFacts(data).length > 0
}

/** What My Plan keeps for one fact (no internal flags). */
export function factSelection(fact, place) {
  return {
    id: fact.id || `${place?.key || ''}:${fact.text}`,
    text: fact.text,
    fact_type: fact.fact_type,
    place: place?.name || null,
    origin: fact.origin === 'crawler' ? 'crawler' : 'ai',
    lang: langAttr(fact.lang),
    value_lang: typeof fact.value_lang === 'string' ? fact.value_lang : null,
    citation: fact.origin === 'crawler' && fact.citation
      ? { name: fact.citation.name || null, url: fact.citation.url || null, as_of: fact.citation.as_of || null, attribution: fact.citation.attribution || null, licence_url: fact.citation.licence_url || null }
      : null,
  }
}

/**
 * A fact's text: in its own language (`lang`) when known, with a quoted
 * value (an official name, a motto) marked in the value's language.
 */
export function FactText({ fact }) {
  const parts = quotedValue(fact.text, fact.value_lang)
  return (
    <span lang={langAttr(fact.lang) || undefined}>
      {parts
        ? <>{parts.before}<span lang={parts.lang}>{parts.value}</span>{parts.after}</>
        : fact.text}
    </span>
  )
}

/**
 * One fact kept in My Plan (drawer, plan view): a crawler fact keeps its
 * source link, as-of date and licence attribution.
 */
export function SelectedFact({ fact, aiLabel, className = 'text-xs' }) {
  if (!fact) return null
  const crawler = fact.origin === 'crawler'
  return (
    <>
      <p className={`${className} text-gray-800`} data-testid="selected-fact">
        {fact.place && <span className="font-medium not-italic">{fact.place}: </span>}
        <FactText fact={fact} />
      </p>
      {crawler && fact.citation
        ? <SourceLine source={fact.citation} className="mt-0.5" />
        : !crawler && <p className="text-[10px] text-amber-700 mt-0.5">{aiLabel}</p>}
    </>
  )
}

function FactCard({ fact, place, selected, onSelect }) {
  const { t } = useTranslation('results')
  const ai = fact.origin !== 'crawler'
  return (
    <li className={`p-3 rounded-lg border bg-white ${selected ? 'border-orange-400 ring-1 ring-orange-300' : 'border-gray-200'}`} data-testid="place-fact">
      <p className="text-sm text-gray-800"><FactText fact={fact} /></p>
      <div className="flex flex-wrap items-center justify-between gap-2 mt-1.5">
        <div className="min-w-0 flex-1">
          {ai ? (
            <span className="inline-flex items-center gap-1 text-[11px] font-medium px-1.5 py-0.5 rounded-full bg-amber-50 text-amber-800 border border-amber-200" data-testid="fact-ai-label">
              <Sparkles size={10} aria-hidden="true" /> {t('facts.aiLabel')}
            </span>
          ) : (
            <>
              <SourceLine source={fact.citation} />
              {fact.machine_translated && <p className="text-[11px] text-gray-400">{t('facts.machineTranslated')}</p>}
            </>
          )}
        </div>
        {onSelect && (
          <button type="button" data-tid="results.fact.add" onClick={() => onSelect('place_facts', factSelection(fact, place))}
            aria-pressed={selected}
            className={`flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-semibold transition-all shrink-0 ${selected ? 'bg-orange-500 text-white' : 'bg-white text-gray-500 hover:bg-orange-50 hover:text-orange-700 border border-gray-200'}`}>
            {selected ? <><Check size={10} /> {t('plan.inPlan')}</> : <><Plus size={10} /> {t('plan.addToPlan')}</>}
          </button>
        )}
      </div>
    </li>
  )
}

export default function PlaceFactsSection({ data, selections, onSelect }) {
  const { t } = useTranslation('results')
  const places = useMemo(() => placesWithFacts(data), [data])
  const [placeKey, setPlaceKey] = useState(null)
  const [group, setGroup] = useState(null)
  if (!places.length) return null

  const place = places.find(p => p.key === placeKey) || places[0]
  const available = FACT_TYPES.filter(ft => place.groups[ft].length)
  const active = available.includes(group) ? group : available[0]
  const facts = place.groups[active] || []
  const selectedIds = new Set((selections?.place_facts || []).map(f => f.id))
  const scopeLabel = (p) => t(`facts.scope.${p.scope}`, { defaultValue: '' })

  return (
    <div className="p-4 space-y-3" data-testid="place-facts">
      {places.length > 1 && (
        <div className="flex flex-wrap gap-1.5" role="group" aria-label={t('facts.placesLabel')}>
          {places.map(p => (
            <button key={p.key} type="button" data-tid="results.facts.place" aria-pressed={p.key === place.key}
              onClick={() => setPlaceKey(p.key)}
              className={`px-3 py-1 rounded-full text-xs font-semibold border transition-colors ${p.key === place.key ? 'bg-orange-500 text-white border-orange-500' : 'bg-white text-gray-600 border-gray-200 hover:bg-orange-50'}`}>
              {p.name}{scopeLabel(p) && <span className="font-normal opacity-80"> · {scopeLabel(p)}</span>}
            </button>
          ))}
        </div>
      )}
      <div className="flex flex-wrap gap-1.5" role="tablist" aria-label={t('facts.groupsLabel')}>
        {available.map(ft => (
          <button key={ft} type="button" role="tab" data-tid="results.facts.group" aria-selected={ft === active}
            onClick={() => setGroup(ft)}
            className={`px-3 py-1 rounded-lg text-xs font-medium border transition-colors ${ft === active ? 'bg-gray-900 text-white border-gray-900' : 'bg-gray-50 text-gray-700 border-gray-200 hover:bg-gray-100'}`}>
            {t(`facts.group.${ft}`)} <span className="opacity-70">({place.groups[ft].length})</span>
          </button>
        ))}
      </div>
      <ul className="space-y-2" role="tabpanel">
        {facts.map((f, i) => (
          <FactCard key={f.id || i} fact={f} place={place}
            selected={selectedIds.has(factSelection(f, place).id)} onSelect={onSelect} />
        ))}
      </ul>
      {facts.some(f => f.origin !== 'crawler') && (
        <p className="text-[11px] text-gray-500">{t('facts.aiNote')}</p>
      )}
    </div>
  )
}
