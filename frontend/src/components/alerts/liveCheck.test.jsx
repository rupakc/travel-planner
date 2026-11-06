// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { MemoryRouter } from 'react-router-dom'

const auth = { token: 'tok', user: { username: 'u', email: 'u@example.com' }, preferences: {} }
vi.mock('../../context/AuthContext', () => ({ useAuth: () => auth, useOptionalAuth: () => auth }))
const alerts = {
  unread: 0, refresh: vi.fn(), caps: { serpapi: true, fareWatch: true, email: true },
  watchesChanged: vi.fn(), markSeen: vi.fn(),
}
vi.mock('../../context/AlertsContext', () => ({ useAlerts: () => alerts }))
vi.mock('../../context/SearchDataContext', () => ({ useSearchData: () => ({ setPendingSearchData: vi.fn() }) }))
vi.mock('../../services/api', () => ({
  listFareWatches: vi.fn(), checkFareWatchNow: vi.fn(), updateFareWatch: vi.fn(), deleteFareWatch: vi.fn(),
  listPriceWatches: vi.fn(), checkPriceWatchNow: vi.fn(), updatePriceWatch: vi.fn(), deletePriceWatch: vi.fn(),
  liveCheckWatch: vi.fn(),
}))
vi.mock('../../utils/analytics', () => ({ track: vi.fn() }))

import * as api from '../../services/api'
import AlertsPage from '../../pages/AlertsPage'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

const FARE = {
  id: 7, status: 'active', origin_label: 'Berlin', destination_label: 'Lisbon', origin_code: 'BER',
  destination_code: 'LIS', departure_date: '2099-12-01', return_date: null, num_travelers: 1,
  baseline_price: 500, last_price: 480, lowest_price: 480, alert_mode: 'any_drop', flexible_days: 0,
  booking_url: 'https://g.co/f', history: [{ price: 500 }, { price: 480 }],
}
const PRICE = {
  status: 'active', baseline_price: 398, last_price: 352, lowest_price: 352, alert_mode: 'any_drop',
  target_price: null, email_enabled: false, check_count: 2, expires_on: '2099-12-10', currency: 'EUR',
  last_observation: { status: 'ok', unit_price: 88 }, history: [{ price: 398 }, { price: 352 }],
}
const HOTEL = { ...PRICE, id: 7, kind: 'hotel', title: 'Lumen Hotel', subtitle: 'Lisbon · 10–14 Dec' }
const ACTIVITY = { ...PRICE, id: 8, kind: 'activity', title: 'Sintra day trip', subtitle: 'Lisbon · 11 Dec' }
const TRIP = { ...PRICE, id: 9, kind: 'trip', title: 'Lisbon trip', subtitle: '10–14 Dec' }
const EXPIRED = { ...PRICE, id: 10, kind: 'hotel', title: 'Old Hotel', status: 'expired' }

const RESULT = {
  kind: 'hotel', watch_id: 7, checked_at: '2026-11-06T18:00:00Z',
  summary: 'Lumen Hotel shows from €412 for 3 nights on Booking.com.\nPrices vary by room.',
  quotes: [
    { label: 'Booking.com, 3 nights', amount: 412.0, currency: 'EUR', source_index: 0 },
    { label: 'Hotel site', amount: 430, currency: 'EUR', source_index: 5 }, // cites nothing usable
  ],
  sources: [{ title: 'Booking.com', uri: 'https://booking.example/lumen' }, { title: 'Bad', uri: 'javascript:x' }],
  searched_for: ['lumen hotel lisbon price 10-14 dec'],
  disclaimer: 'From a live web search just now. Prices change quickly — check the provider before booking. Not used for your price alerts.',
}

let container, root
const button = (text, scope = container) => [...scope.querySelectorAll('button')].find(b => b.textContent.includes(text))
const flush = async () => { await act(async () => { await new Promise(r => setTimeout(r, 0)) }) }
const render = async () => {
  await act(async () => root.render(<MemoryRouter initialEntries={['/alerts']}><AlertsPage /></MemoryRouter>))
  await flush()
}

beforeEach(() => {
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
  window.matchMedia = window.matchMedia || (() => ({ matches: false }))
  Element.prototype.scrollIntoView = vi.fn()
  for (const fn of Object.values(api)) fn.mockReset?.()
  api.listFareWatches.mockResolvedValue([FARE])
  api.listPriceWatches.mockResolvedValue([HOTEL, ACTIVITY, TRIP, EXPIRED])
})
afterEach(() => {
  act(() => root.unmount())
  container.remove()
  vi.restoreAllMocks()
})

describe('Search the web now', () => {
  it('is on every active fare and price watch card, with the right kind', async () => {
    api.liveCheckWatch.mockResolvedValue({ ...RESULT, quotes: [], sources: [], searched_for: [] })
    await render()
    const cases = [['#watch-7', 'flight', 7], ['#price-watch-7', 'hotel', 7], ['#price-watch-8', 'activity', 8], ['#price-watch-9', 'trip', 9]]
    for (const [sel, kind, id] of cases) {
      const card = container.querySelector(sel)
      expect(card, sel).not.toBeNull()
      await act(async () => button('Search the web now', card).click())
      await flush()
      expect(api.liveCheckWatch).toHaveBeenLastCalledWith(kind, id, 'tok')
    }
    // Not offered once a watch has expired
    expect(button('Search the web now', container.querySelector('#price-watch-10'))).toBeUndefined()
  })

  it('shows the summary unmodified, quotes with sources, searched-for links, sources and the disclaimer', async () => {
    api.liveCheckWatch.mockResolvedValue(RESULT)
    await render()
    const card = container.querySelector('#price-watch-7')
    const priceBefore = card.querySelector('.text-3xl').textContent
    await act(async () => button('Search the web now', card).click())
    await flush()

    const panel = card.querySelector('[data-testid="live-check-panel"]')
    expect(panel.querySelector('[data-testid="live-check-summary"]').textContent).toBe(RESULT.summary)
    expect(panel.textContent).toMatch(/€412\.00/)
    expect(panel.textContent).toMatch(/Booking\.com, 3 nights/)
    const links = [...panel.querySelectorAll('a')]
    const quoteLink = links.find(a => a.textContent === 'Booking.com')
    expect(quoteLink.getAttribute('href')).toBe('https://booking.example/lumen')
    expect(quoteLink.getAttribute('rel')).toBe('noopener noreferrer')
    const searched = links.find(a => a.textContent === 'lumen hotel lisbon price 10-14 dec')
    expect(searched.getAttribute('href')).toBe('https://www.google.com/search?q=lumen%20hotel%20lisbon%20price%2010-14%20dec')
    expect(searched.getAttribute('target')).toBe('_blank')
    expect(panel.innerHTML).not.toMatch(/javascript:/)
    expect(panel.textContent).toMatch(/Sources/)
    expect(panel.textContent).toContain(RESULT.disclaimer)
    expect(document.activeElement.textContent).toMatch(/Live web search/)

    // Never feeds the watch: price and history untouched, no watch API called
    expect(card.querySelector('.text-3xl').textContent).toBe(priceBefore)
    expect(api.checkPriceWatchNow).not.toHaveBeenCalled()
    expect(api.updatePriceWatch).not.toHaveBeenCalled()
  })

  it('announces briefly and leaves focus alone when the user has moved on', async () => {
    let resolve
    api.liveCheckWatch.mockReturnValue(new Promise(r => { resolve = r }))
    await render()
    const card = container.querySelector('#price-watch-7')
    await act(async () => button('Search the web now', card).click())
    expect(card.querySelector('[data-testid="live-check-status"]').textContent).toBe('Searching the web…')
    // Only the short status line is live, never the whole panel
    expect(card.querySelector('[data-testid="live-check-region"]').getAttribute('aria-live')).toBeNull()
    const elsewhere = button('Search the web now', container.querySelector('#price-watch-9'))
    elsewhere.focus()
    await act(async () => { resolve(RESULT) })
    expect(card.querySelector('[data-testid="live-check-panel"]')).not.toBeNull()
    expect(card.querySelector('[data-testid="live-check-status"]').textContent).toBe('Live web search result ready.')
    expect(document.activeElement).toBe(elsewhere)
  })

  it('can be dismissed, returning focus to the button', async () => {
    api.liveCheckWatch.mockResolvedValue(RESULT)
    await render()
    const card = container.querySelector('#watch-7')
    await act(async () => button('Search the web now', card).click())
    await flush()
    expect(card.querySelector('[data-testid="live-check-panel"]')).not.toBeNull()
    await act(async () => card.querySelector('[aria-label="Dismiss the web search result"]').click())
    expect(card.querySelector('[data-testid="live-check-panel"]')).toBeNull()
    expect(document.activeElement).toBe(button('Search the web now', card))
  })

  it('shows a loading state while searching', async () => {
    let resolve
    api.liveCheckWatch.mockReturnValue(new Promise(r => { resolve = r }))
    await render()
    const card = container.querySelector('#price-watch-9')
    await act(async () => button('Search the web now', card).click())
    expect(button('Searching the web…', card).disabled).toBe(true)
    expect(card.querySelector('[data-testid="live-check-loading"]')).not.toBeNull()
    await act(async () => { resolve(RESULT) })
    expect(card.querySelector('[data-testid="live-check-loading"]')).toBeNull()
  })

  it.each([
    [404, 'Watch not found', /no longer exists/, false],
    [429, 'Too many requests — please wait 12 seconds.', /please wait 12 seconds/, true],
    [409, { code: 'watch_expired', message: 'Expired.' }, /dates have passed, so there’s nothing live to check/, false],
    [503, { code: 'ai_limit', message: 'AI limit reached for this month — try again on the 1st.' }, /AI limit reached/, false],
    [503, { code: 'ai_billing', message: 'AI features are unavailable right now.' }, /unavailable right now/, false],
    [503, { code: 'grounding_unavailable', message: 'Live web and map results need the Gemini provider.' }, /Live web search isn’t available/, false],
    [502, { code: 'live_check_failed', message: 'We couldn’t get a live answer this time.' }, /couldn’t get a live answer/, true],
  ])('maps a %i error to friendly copy', async (status, detail, text, retry) => {
    api.liveCheckWatch.mockRejectedValue({ response: { status, data: { detail } } })
    await render()
    const card = container.querySelector('#price-watch-8')
    await act(async () => button('Search the web now', card).click())
    await flush()
    const alert = card.querySelector('[role="alert"]')
    expect(alert.textContent).toMatch(text)
    expect(!!button('Try again', alert)).toBe(retry)
    expect(card.querySelector('[data-testid="live-check-panel"]')).toBeNull()
  })

  it('never writes results to storage', async () => {
    const setItem = vi.spyOn(Storage.prototype, 'setItem')
    api.liveCheckWatch.mockResolvedValue(RESULT)
    await render()
    await act(async () => button('Search the web now', container.querySelector('#price-watch-7')).click())
    await flush()
    expect(container.querySelector('[data-testid="live-check-panel"]')).not.toBeNull()
    expect(setItem).not.toHaveBeenCalled()
  })
})
