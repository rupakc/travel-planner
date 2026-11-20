// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import PlaceFactsSection, { hasPlaceFacts, placesWithFacts, factSelection, SelectedFact } from './PlaceFactsSection'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

const empty = () => ({ historical: [], fun: [], popular: [], unbelievable: [], little_known: [] })
const crawlerFact = {
  id: 'c:1', fact_type: 'historical', text: 'Berlin was founded in 1237.', origin: 'crawler', source: 'crawler',
  citation: { name: 'Wikidata', url: 'https://www.wikidata.org/wiki/Q64#P571', as_of: '2026-11-20', licence: 'open', attribution: 'Wikidata (CC0 1.0)' },
}
// The crawler sends no fun facts: the fun group here is AI-suggested
const motto = {
  id: 'c:3', fact_type: 'popular', text: 'Berlin’s motto is “Berlin bleibt doch Berlin”.', origin: 'crawler', lang: 'en', value_lang: 'de',
  citation: { name: 'Wikidata', url: 'https://www.wikidata.org/wiki/Q64#P1451', licence: 'open', attribution: 'Wikidata (CC0 1.0)' },
}
const aiFun = { id: 'a:2', fact_type: 'fun', text: 'Berlin has a museum just for currywurst.', origin: 'ai', source: 'ai', verified: false, citation: null }
const aiFact = { id: 'a:1', fact_type: 'unbelievable', text: 'Berlin has more bridges than Venice.', origin: 'ai', source: 'ai', verified: false, citation: null }
const section = () => ({
  places: [
    { key: 'city:2950159', scope: 'city', name: 'Berlin', groups: { ...empty(), historical: [crawlerFact], fun: [aiFun], popular: [motto], unbelievable: [aiFact] } },
    { key: 'country:DE', scope: 'country', name: 'Germany', groups: { ...empty(), popular: [{ ...crawlerFact, id: 'c:10', fact_type: 'popular', text: 'Germany has about 83 million people.' }] } },
    { key: 'region:DE.02', scope: 'region', name: 'Bavaria', groups: empty() },
  ],
})

describe('PlaceFactsSection', () => {
  let container, root
  const render = (el) => act(() => root.render(el))
  const click = (el) => act(() => el.dispatchEvent(new MouseEvent('click', { bubbles: true })))

  beforeEach(() => {
    container = document.createElement('div')
    document.body.appendChild(container)
    root = createRoot(container)
  })
  afterEach(() => {
    act(() => root.unmount())
    container.remove()
  })

  it('hides itself without facts (older backend, error, empty)', () => {
    for (const data of [undefined, null, { error: 'x' }, { places: [] }, { places: [{ key: 'k', groups: empty() }] }]) {
      expect(hasPlaceFacts(data)).toBe(false)
      render(<PlaceFactsSection data={data} />)
      expect(container.innerHTML).toBe('')
    }
  })

  it('drops places with no facts and keeps the five groups', () => {
    const places = placesWithFacts(section())
    expect(places.map(p => p.key)).toEqual(['city:2950159', 'country:DE'])
    expect(Object.keys(places[0].groups)).toEqual(['historical', 'fun', 'popular', 'unbelievable', 'little_known'])
  })

  it('shows the crawler source line and switches groups', () => {
    render(<PlaceFactsSection data={section()} />)
    const groups = [...container.querySelectorAll('[data-tid="results.facts.group"]')]
    expect(groups.map(g => g.textContent)).toEqual(['Historical (1)', 'Fun (1)', 'Popular (1)', 'Unbelievable (1)'])
    expect(container.textContent).toContain('Berlin was founded in 1237.')
    const link = container.querySelector('[data-testid="official-source"] a')
    expect(link.getAttribute('href')).toBe('https://www.wikidata.org/wiki/Q64#P571')
    expect(container.textContent).toContain('Wikidata (CC0 1.0)')
    expect(container.querySelector('[data-testid="fact-ai-label"]')).toBeNull()

    click(groups[3])
    expect(container.textContent).toContain('Berlin has more bridges than Venice.')
    expect(container.querySelector('[data-testid="fact-ai-label"]').textContent).toContain('AI-suggested, not verified')
    // an AI fact never shows a link
    expect(container.querySelector('[data-testid="place-fact"] a')).toBeNull()
  })

  it('switches places in a multi-place section', () => {
    render(<PlaceFactsSection data={section()} />)
    const places = [...container.querySelectorAll('[data-tid="results.facts.place"]')]
    expect(places).toHaveLength(2)
    click(places[1])
    expect(container.textContent).toContain('Germany has about 83 million people.')
  })

  it('the fun group is AI-suggested', () => {
    render(<PlaceFactsSection data={section()} />)
    click(container.querySelectorAll('[data-tid="results.facts.group"]')[1])
    expect(container.textContent).toContain('Berlin has a museum just for currywurst.')
    expect(container.querySelector('[data-testid="fact-ai-label"]').textContent).toContain('AI-suggested, not verified')
    expect(container.querySelector('[data-testid="place-fact"] a')).toBeNull()
  })

  it('marks the text and a quoted value with their languages', () => {
    render(<PlaceFactsSection data={section()} />)
    click(container.querySelectorAll('[data-tid="results.facts.group"]')[2])
    const card = container.querySelector('[data-testid="place-fact"]')
    expect(card.querySelector('[lang="en"]').textContent).toBe('Berlin’s motto is “Berlin bleibt doch Berlin”.')
    expect(card.querySelector('[lang="de"]').textContent).toBe('Berlin bleibt doch Berlin')
    expect(card.querySelector('q')).toBeNull()
  })

  it('tolerates facts without language tags', () => {
    render(<PlaceFactsSection data={section()} />)
    const card = container.querySelector('[data-testid="place-fact"]')
    expect(card.textContent).toContain('Berlin was founded in 1237.')
    expect(card.querySelector('[lang]')).toBeNull()
  })

  it('adds a fact to My Plan with its citation', () => {
    const onSelect = vi.fn()
    render(<PlaceFactsSection data={section()} selections={{ place_facts: [] }} onSelect={onSelect} />)
    click(container.querySelector('[data-tid="results.fact.add"]'))
    expect(onSelect).toHaveBeenCalledWith('place_facts', expect.objectContaining({
      id: 'c:1', place: 'Berlin', origin: 'crawler', text: 'Berlin was founded in 1237.',
      citation: expect.objectContaining({ name: 'Wikidata', url: 'https://www.wikidata.org/wiki/Q64#P571' }),
    }))
    render(<PlaceFactsSection data={section()} selections={{ place_facts: [{ id: 'c:1' }] }} onSelect={onSelect} />)
    expect(container.querySelector('[data-tid="results.fact.add"]').getAttribute('aria-pressed')).toBe('true')
  })

  it('never gives an AI fact a citation in the plan', () => {
    expect(factSelection({ ...aiFact, citation: { name: 'Made up', url: 'https://x.example' } }, { name: 'Berlin' }).citation).toBeNull()
  })

  it('a fact in My Plan keeps its languages, source link and licence attribution (drawer)', () => {
    const kept = factSelection(motto, { name: 'Berlin' })
    expect(kept).toEqual(expect.objectContaining({ lang: 'en', value_lang: 'de' }))
    expect(kept).not.toHaveProperty('quote')
    render(<SelectedFact fact={kept} aiLabel="AI-suggested" />)
    expect(container.querySelector('[data-testid="selected-fact"] [lang="de"]').textContent).toBe('Berlin bleibt doch Berlin')
    const hrefs = [...container.querySelectorAll('a')].map((a) => a.getAttribute('href'))
    expect(hrefs).toContain('https://www.wikidata.org/wiki/Q64#P1451')
    expect(container.textContent).toContain('Wikidata (CC0 1.0)')
    expect(container.textContent).not.toContain('AI-suggested')
  })

  it('a fact without language tags keeps null ones in My Plan', () => {
    expect(factSelection(crawlerFact, { name: 'Berlin' })).toEqual(expect.objectContaining({ lang: null, value_lang: null }))
  })

  it('a stored fact with a script link gets no link (drawer)', () => {
    render(<SelectedFact fact={{ id: 'c:9', text: 'Some fact text here.', origin: 'crawler', citation: { name: 'X', url: 'javascript:alert(1)', licence_url: 'javascript:alert(2)', attribution: 'X (CC0)' } }} aiLabel="AI" />)
    expect(container.querySelector('a')).toBeNull()
    expect(container.textContent).toContain('X (CC0)')
  })

  it('an AI fact in My Plan shows the AI label and no link (drawer)', () => {
    render(<SelectedFact fact={factSelection(aiFact, { name: 'Berlin' })} aiLabel="AI-suggested, not verified" />)
    expect(container.querySelector('a')).toBeNull()
    expect(container.textContent).toContain('AI-suggested, not verified')
  })
})
