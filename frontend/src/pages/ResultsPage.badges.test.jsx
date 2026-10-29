// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach } from 'vitest'
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { HotelsSection, ActivitiesSection, PlacesToSeeSection } from './ResultsPage'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

const count = (el) => (el.textContent.match(/Found online/g) || []).length

describe('Found online badge on result cards', () => {
  let container, root
  beforeEach(() => {
    container = document.createElement('div')
    document.body.appendChild(container)
    root = createRoot(container)
  })
  afterEach(() => {
    act(() => root.unmount())
    container.remove()
  })
  const props = { selections: { activities: [], places_to_see: [] }, onSelect: () => {} }

  it.each([
    ['hotel', (item) => <HotelsSection data={{ results: [item] }} {...props} />, { name: 'H', price_per_night_usd: 100 }],
    ['activity', (item) => <ActivitiesSection data={{ results: [item] }} {...props} />, { name: 'A', category: 'food', description: 'd' }],
    ['place', (item) => <PlacesToSeeSection data={{ results: [item] }} {...props} />, { name: 'P', description: 'd' }],
  ])('%s card shows exactly one badge when link_verified is true, none otherwise', (_n, make, base) => {
    act(() => root.render(make({ ...base, link_verified: true })))
    expect(count(container)).toBe(1)
    act(() => root.render(make({ ...base, link_verified: false })))
    expect(count(container)).toBe(0)
  })
})
