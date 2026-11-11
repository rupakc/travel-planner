// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { MemoryRouter, useLocation } from 'react-router-dom'

const auth = { token: 't', user: { username: 'jane' }, preferences: null, updatePreferences: vi.fn() }
const journey = { enabled: false }
const tourState = { opts: null, start: vi.fn() }
vi.mock('../context/AuthContext', () => ({ useAuth: () => auth }))
vi.mock('../context/SearchDataContext', () => ({
  useSearchData: () => ({ setPendingSearchData: vi.fn(), hasSearchResults: false, clearSearchResults: vi.fn() }),
}))
vi.mock('../hooks/useJourney', () => ({ useJourney: () => journey }))
vi.mock('../hooks/useFirstRunTour', () => ({
  default: (opts) => { tourState.opts = opts; return { open: false, start: tourState.start, close: vi.fn() } },
}))
vi.mock('../services/api', () => ({
  discoverDestinations: vi.fn(), compareDestination: vi.fn(),
  getRecentSearches: vi.fn(() => Promise.resolve([])), saveRecentSearch: vi.fn(), deleteRecentSearch: vi.fn(),
}))
vi.mock('../components/ui/AirportSearch', () => ({
  default: ({ value, ...p }) => <input data-testid={`ap-${String(p.label?.props?.children?.[2] ?? '').trim() || 'x'}`} data-dest={value} readOnly value={value || ''} />,
}))

import i18n from '../i18n'
import SearchPage from './SearchPage'

globalThis.IS_REACT_ACT_ENVIRONMENT = true
let container, root, here
function Where() { here = useLocation(); return null }
const q = (tid) => container.querySelector(`[data-tid="${tid}"]`)

async function mount(entry = '/explore') {
  container = document.createElement('div'); document.body.appendChild(container)
  root = createRoot(container)
  await act(async () => root.render(
    <MemoryRouter initialEntries={[entry]}><Where /><SearchPage /></MemoryRouter>))
}
beforeEach(() => { journey.enabled = false; tourState.opts = null; localStorage.clear() })
afterEach(async () => {
  act(() => root.unmount()); container.remove()
  await act(async () => { await i18n.changeLanguage('en') })
})

describe('SearchPage explore entry', () => {
  for (const lng of ['de', 'bn']) {
    it(`mode row scrolls sideways instead of wrapping (${lng}, flag off and on)`, async () => {
      await act(async () => { await i18n.changeLanguage(lng) })
      for (const on of [false, true]) {
        journey.enabled = on
        await mount()
        const row = q('search.modes')
        expect(row.className).toContain('overflow-x-auto')
        expect(row.className).toContain('whitespace-nowrap')
        expect(row.className).toContain('snap-x')
        expect(row.className).not.toContain('flex-wrap')
        act(() => root.unmount()); container.remove()
      }
      await mount() // so afterEach has something to unmount
    })
  }

  it('flag off: classic four modes, no Chat chip', async () => {
    await mount()
    expect(q('search.mode-chat')).toBeNull()
    expect(q('search.mode-nearby')).toBeNull()
    expect(q('search.tour-start')).not.toBeNull()
  })

  it('journey on: Chat chip goes to /chat, Near me to /nearby', async () => {
    journey.enabled = true
    await mount()
    expect(container.querySelector('h1').textContent).toBe('Explore')
    await act(async () => q('search.mode-chat').click())
    expect(here.pathname).toBe('/chat')
    await act(async () => q('search.mode-nearby').click())
    expect(here.pathname).toBe('/nearby')
  })

  it('prefill sets the destination', async () => {
    journey.enabled = true
    await mount({ pathname: '/explore', state: { prefill: { destination: 'Lisbon, Portugal' } } })
    const dest = [...container.querySelectorAll('input[data-dest]')].map((i) => i.value)
    expect(dest).toContain('Lisbon, Portugal')
  })

  it('search tour is not eligible with the journey on', async () => {
    journey.enabled = true
    await mount('/')
    expect(tourState.opts.visible).toBe(false)
    expect(q('search.tour-start')).toBeNull()
  })

  it('flag off: tour stays eligible on /', async () => {
    await mount('/')
    expect(tourState.opts.visible).toBe(true)
  })
})
