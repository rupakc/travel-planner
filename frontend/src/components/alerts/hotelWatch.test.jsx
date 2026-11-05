// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { MemoryRouter, Routes, Route, useLocation } from 'react-router-dom'

const auth = { token: 'tok', user: { username: 'u', email: 'u@example.com' }, preferences: {} }
vi.mock('../../context/AuthContext', () => ({ useAuth: () => auth, useOptionalAuth: () => auth }))

const alerts = {
  caps: { serpapi: true, fareWatch: true, email: true },
  watchesChanged: vi.fn(), shouldOfferBrowserAlerts: vi.fn(() => false), answerBrowserAlerts: vi.fn(),
  priceWatchFor: vi.fn(async () => null),
}
vi.mock('../../context/AlertsContext', async () => {
  const { useState, useEffect } = await import('react')
  return {
    useAlerts: () => alerts,
    usePriceWatchFor: (kind, spec) => {
      const [w, setW] = useState(null)
      useEffect(() => { alerts.priceWatchFor(kind, spec).then(setW) }, [])
      return [w, setW]
    },
  }
})
vi.mock('../../services/api', () => ({ createPriceWatch: vi.fn(), deletePriceWatch: vi.fn() }))
vi.mock('../../utils/analytics', () => ({ track: vi.fn() }))

import * as api from '../../services/api'
import WatchHotelButton from './WatchHotelButton'
import HotelDialogBody from './dialogs/HotelDialogBody'
import PriceWatchDialog from './PriceWatchDialog'
import HotelWatchCard from './cards/HotelWatchCard'
import { cardFor } from './cards'
import { dialogBodyFor } from './dialogs'
import { alertKindFor, kindOf } from './alertKinds'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

const SEARCH = { destination: 'Lisbon, Portugal', departure_date: '2099-12-10', return_date: '2099-12-14', adults: 2, num_travelers: 2 }
const HOTEL = { name: 'Lumen Hotel', price_per_night_usd: 100, total_price_usd: 410 }
const SPEC = { name: 'Lumen Hotel', city: 'Lisbon, Portugal', check_in: '2099-12-10', check_out: '2099-12-14', adults: 2, rooms: 1, estimate_total: 410 }
const WATCH = {
  id: 11, kind: 'hotel', status: 'active', title: 'Lumen Hotel & The Lisbon Light Show', subtitle: '10–14 Dec · 2 guests · 1 room',
  currency: 'USD', baseline_price: 398, last_price: 398, lowest_price: 398, alert_mode: 'any_drop', target_price: null,
  email_enabled: false, check_count: 1, expires_on: '2099-12-10', link: 'https://www.lumenhotel.pt/',
  subject: { name: 'Lumen Hotel & The Lisbon Light Show', requested_name: 'Lumen Hotel', city: 'Lisbon, Portugal', property_token: 'tok', check_in: '2099-12-10', check_out: '2099-12-14', adults: 2, rooms: 1 },
  last_observation: { status: 'ok', unit_price: 99.5, source: 'google_hotels', link: 'https://www.lumenhotel.pt/' },
  history: [{ price: 398 }],
}

let container, root, location
function Where() { location = useLocation(); return null }
const render = async (el, path = '/results') => {
  await act(async () => root.render(
    <MemoryRouter initialEntries={[path]}>
      <Routes><Route path="*" element={<>{el}<Where /></>} /></Routes>
    </MemoryRouter>,
  ))
}
const button = (text, scope = document.body) => [...scope.querySelectorAll('button')].find(b => b.textContent.includes(text))

beforeEach(() => {
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
  auth.token = 'tok'
  alerts.caps = { serpapi: true, fareWatch: true, email: true }
  alerts.priceWatchFor.mockReset().mockResolvedValue(null)
  alerts.watchesChanged.mockReset()
  api.createPriceWatch.mockReset()
  api.deletePriceWatch.mockReset()
})
afterEach(() => {
  act(() => root.unmount())
  container.remove()
  document.body.innerHTML = ''
})

describe('WatchHotelButton', () => {
  it('renders nothing without live prices or when the stay has no dates', async () => {
    alerts.caps = { ...alerts.caps, fareWatch: false }
    await render(<WatchHotelButton hotel={HOTEL} searchData={SEARCH} />)
    expect(container.textContent).toBe('')
    alerts.caps = { ...alerts.caps, fareWatch: true }
    await render(<WatchHotelButton hotel={HOTEL} searchData={{ ...SEARCH, return_date: null }} />)
    expect(container.textContent).toBe('')
    await render(<WatchHotelButton hotel={HOTEL} searchData={{ ...SEARCH, departure_date: '2000-01-01' }} />)
    expect(container.textContent).toBe('')
  })

  it('sends a signed-out traveller to sign in and back', async () => {
    auth.token = null
    await render(<WatchHotelButton hotel={HOTEL} searchData={SEARCH} />, '/results?x=1')
    const b = button('Watch price')
    expect(b.getAttribute('aria-label')).toBe('Watch price of Lumen Hotel — sign in first')
    await act(async () => b.click())
    expect(location.pathname).toBe('/login')
    expect(new URLSearchParams(location.search).get('next')).toBe('/results?x=1')
    expect(alerts.priceWatchFor).not.toHaveBeenCalled()
  })

  it('looks up its own stay and shows “Watching · $398” once watched', async () => {
    alerts.priceWatchFor.mockResolvedValue(WATCH)
    await render(<WatchHotelButton hotel={HOTEL} searchData={SEARCH} />)
    expect(alerts.priceWatchFor).toHaveBeenCalledWith('hotel', SPEC)
    const b = button('Watching')
    expect(b.textContent).toBe('Watching · $398')
    expect(b.getAttribute('aria-label')).toContain('Lumen Hotel — open your alerts')
    await act(async () => b.click())
    expect(location.pathname + location.search).toBe('/alerts?kind=hotel&watch=11')
  })

  it('shows a paused watch as paused, and an ended one as watchable again', async () => {
    alerts.priceWatchFor.mockResolvedValue({ ...WATCH, status: 'paused' })
    await render(<WatchHotelButton hotel={HOTEL} searchData={SEARCH} />)
    expect(button('Watch paused')).toBeTruthy()
    alerts.priceWatchFor.mockResolvedValue({ ...WATCH, status: 'error' })
    act(() => root.unmount())
    root = createRoot(container)
    await render(<WatchHotelButton hotel={HOTEL} searchData={SEARCH} />)
    expect(button('Watch on hold')).toBeTruthy()
    expect(button('Watching')).toBeUndefined()
    alerts.priceWatchFor.mockResolvedValue({ ...WATCH, status: 'expired' })
    act(() => root.unmount())
    root = createRoot(container)
    await render(<WatchHotelButton hotel={HOTEL} searchData={SEARCH} />)
    expect(button('Watch price')).toBeTruthy()
  })

  it('opens the hotel dialog without selecting the card, and creates the watch', async () => {
    const onCard = vi.fn()
    api.createPriceWatch.mockResolvedValue({ ...WATCH, already_watching: false })
    await render(<div onClick={onCard}><WatchHotelButton hotel={HOTEL} searchData={SEARCH} /></div>)
    await act(async () => button('Watch price').click())
    const dialog = document.querySelector('[role="dialog"]')
    expect(dialog.textContent).toContain('Watch this hotel')
    expect(dialog.textContent).toContain('10–14 Dec · 4 nights · 2 guests · 1 room')
    expect(dialog.textContent).toContain('$410')
    expect(dialog.textContent).toContain('AI estimate for 1 room, whole stay')
    // The estimate never seeds the target
    await act(async () => dialog.querySelector('input[value="below_target"]').click())
    expect(dialog.querySelector('input[aria-label^="Target price"]').value).toBe('')
    await act(async () => dialog.querySelector('input[value="any_drop"]').click())
    await act(async () => button('Start watching', dialog).click())
    expect(onCard).not.toHaveBeenCalled()
    expect(api.createPriceWatch).toHaveBeenCalledWith({
      kind: 'hotel', hotel: SPEC, alert_mode: 'any_drop', target_price: null, email_enabled: false,
    }, 'tok')
    const done = document.querySelector('[role="dialog"]')
    expect(done.textContent).toContain('Tracking: Lumen Hotel & The Lisbon Light Show on Google Hotels')
    await act(async () => button('Done', done).click())
    expect(button('Watching').textContent).toBe('Watching · $398')
  })
})

describe('HotelDialogBody', () => {
  it('is the registered hotel body', () => {
    expect(dialogBodyFor('hotel')).toBe(HotelDialogBody)
  })

  it('labels the page’s price as an estimate before the live look', async () => {
    await render(<HotelDialogBody spec={SPEC} preview={{ title: 'Lumen Hotel', subtitle: '10–14 Dec · 4 nights · 2 guests · 1 room', price: null, estimate: 410, estimateLabel: 'AI estimate for 1 room, whole stay' }} />)
    expect(container.textContent).toContain('Shown now $410AI estimate for 1 room, whole stay')
    expect(container.textContent).toContain('We’ll find Lumen Hotel on Google Hotels in Lisbon and watch its live price for 10–14 Dec · 4 nights · 2 guests · 1 room.')
  })

  it('shows the tracked property, total and nightly, and says when the name differs', async () => {
    await render(<HotelDialogBody spec={SPEC} watch={WATCH} />)
    const text = container.textContent
    expect(text).toContain('Tracking: Lumen Hotel & The Lisbon Light Show on Google Hotels')
    expect(text).toContain('$398 for 4 nights · $99.50 a night · 10–14 Dec · 2 guests · 1 room')
    expect(text).toContain('Your plan calls it “Lumen Hotel”; Google Hotels lists it as “Lumen Hotel & The Lisbon Light Show”.')
  })

  it('without alternatives, “Remove it” goes to Alerts and closes the dialog', async () => {
    const onClose = vi.fn()
    await render(<HotelDialogBody spec={SPEC} watch={WATCH} onClose={onClose} />)
    const link = [...container.querySelectorAll('a')].find(a => a.textContent.includes('Remove it'))
    expect(link.getAttribute('href')).toBe('/alerts?kind=hotel&watch=11')
    await act(async () => link.click())
    expect(onClose).toHaveBeenCalled()
    expect(location.pathname).toBe('/alerts')
  })

  it('“Not this one?” offers the other properties and swaps the watch', async () => {
    const ALT = {
      title: 'Brown’s Avenue Hotel', subtitle: '4★ · $120 a night · total for 4 nights', price: 480, currency: 'USD',
      spec: { name: 'Brown’s Avenue Hotel', city: 'Lisbon, Portugal', check_in: '2099-12-10', check_out: '2099-12-14', adults: 2, rooms: 1, property_token: 'b' },
    }
    const watched = { ...WATCH, alert_mode: 'below_target', target_price: 350, email_enabled: true,
      last_observation: { ...WATCH.last_observation, observed: { alternatives: [ALT] } } }
    const swapped = { ...WATCH, id: 12, title: 'Brown’s Avenue Hotel', baseline_price: 480, last_price: 480,
      subject: { ...ALT.spec, requested_name: 'Brown’s Avenue Hotel' }, last_observation: { status: 'ok', unit_price: 120 } }
    api.deletePriceWatch.mockResolvedValue()
    api.createPriceWatch.mockResolvedValue(swapped)
    await render(<HotelDialogBody spec={SPEC} watch={watched} onClose={vi.fn()} />)
    expect(container.textContent).not.toContain('Remove it')
    const toggle = button('Not this one?')
    expect(toggle.getAttribute('aria-expanded')).toBe('false')
    await act(async () => toggle.click())
    expect(toggle.getAttribute('aria-expanded')).toBe('true')
    expect(container.textContent).toContain('Brown’s Avenue Hotel')
    expect(container.textContent).toContain('$480')
    await act(async () => button('Watch this instead').click())
    expect(api.deletePriceWatch).toHaveBeenCalledWith(11, 'tok')
    expect(api.createPriceWatch).toHaveBeenCalledWith({
      kind: 'hotel', hotel: ALT.spec, alert_mode: 'below_target', target_price: 350, email_enabled: true,
    }, 'tok')
    expect(alerts.watchesChanged).toHaveBeenCalled()
    expect(container.textContent).toContain('Tracking: Brown’s Avenue Hotel on Google Hotels')
    expect(button('Not this one?')).toBeUndefined()
  })

  it('reports the replacement watch to the dialog through onReplaced', async () => {
    const ALT = { title: 'Other', price: 300, spec: { name: 'Other', property_token: 'o' } }
    const watched = { ...WATCH, last_observation: { ...WATCH.last_observation, observed: { alternatives: [ALT] } } }
    const next = { ...WATCH, id: 12, title: 'Other', last_observation: { status: 'ok' } }
    api.createPriceWatch.mockResolvedValue(next)
    api.deletePriceWatch.mockResolvedValue()
    const onReplaced = vi.fn()
    await render(<HotelDialogBody spec={SPEC} watch={watched} onReplaced={onReplaced} />)
    await act(async () => button('Not this one?').click())
    await act(async () => button('Watch this instead').click())
    expect(onReplaced).toHaveBeenCalledWith(next, { spec: ALT.spec })
  })

  it('after a swap the dialog header, subtitle and “See your alerts” follow the new watch', async () => {
    const ALT = {
      title: 'Brown’s Avenue Hotel', subtitle: '4★ · $120 a night · total for 4 nights', price: 480, currency: 'USD',
      spec: { name: 'Brown’s Avenue Hotel', city: 'Lisbon, Portugal', check_in: '2099-12-10', check_out: '2099-12-14', adults: 2, rooms: 1, property_token: 'b' },
    }
    const first = { ...WATCH, already_watching: false,
      last_observation: { ...WATCH.last_observation, observed: { alternatives: [ALT] } } }
    const swapped = { ...WATCH, id: 12, title: 'Brown’s Avenue Hotel', subtitle: '10–14 Dec · 2 guests · 1 room (Brown’s)',
      baseline_price: 480, last_price: 480, subject: { ...ALT.spec, requested_name: 'Brown’s Avenue Hotel' },
      last_observation: { status: 'ok', unit_price: 120 } }
    api.createPriceWatch.mockResolvedValueOnce(first).mockResolvedValueOnce(swapped)
    api.deletePriceWatch.mockResolvedValue()
    const onWatched = vi.fn()
    await render(<PriceWatchDialog kind="hotel" spec={SPEC} preview={{ title: 'Lumen Hotel', price: null }} onClose={vi.fn()} onWatched={onWatched} />)
    await act(async () => button('Start watching').click())
    const dialog = () => document.querySelector('[role="dialog"]')
    expect(dialog().textContent).toContain(WATCH.title)
    await act(async () => button('Not this one?').click())
    await act(async () => button('Watch this instead').click())
    const text = dialog().textContent
    expect(text).toContain('Watching this hotel')
    expect(text).toContain('Brown’s Avenue Hotel · 10–14 Dec · 2 guests · 1 room (Brown’s)')
    expect(text).not.toContain(WATCH.title)
    expect(text).toContain('The live price is $480')
    const link = [...dialog().querySelectorAll('a')].find(a => a.textContent.includes('See your alerts'))
    expect(link.getAttribute('href')).toBe('/alerts?kind=hotel&watch=12')
    expect(onWatched).toHaveBeenLastCalledWith(swapped, { spec: ALT.spec, viaSuggestion: true })
    expect(button('Not this one?')).toBeUndefined()
  })

  it('keeps the first watch and says so when the swap fails', async () => {
    const ALT = { title: 'Other', price: 300, spec: { name: 'Other', property_token: 'o' } }
    const watched = { ...WATCH, last_observation: { ...WATCH.last_observation, observed: { alternatives: [ALT] } } }
    api.createPriceWatch.mockRejectedValue(new Error('boom'))
    api.deletePriceWatch.mockResolvedValue()
    await render(<HotelDialogBody spec={SPEC} watch={watched} />)
    await act(async () => button('Not this one?').click())
    await act(async () => button('Watch this instead').click())
    expect(api.deletePriceWatch).not.toHaveBeenCalled()
    expect(container.querySelector('[role="alert"]').textContent).toContain('Couldn’t switch')
    expect(container.textContent).toContain('Tracking: Lumen Hotel & The Lisbon Light Show')
  })

  it('at the active-watch limit, makes room first and then swaps (M10)', async () => {
    const ALT = { title: 'Other', price: 300, spec: { name: 'Other', property_token: 'o' } }
    const watched = { ...WATCH, last_observation: { ...WATCH.last_observation, observed: { alternatives: [ALT] } } }
    const next = { ...WATCH, id: 12, title: 'Other', last_observation: { status: 'ok' } }
    const order = []
    api.createPriceWatch.mockReset()
      .mockImplementationOnce(async () => { order.push('create'); throw { response: { status: 409, data: { detail: 'limit' } } } })
      .mockImplementationOnce(async () => { order.push('create'); return next })
    api.deletePriceWatch.mockReset().mockImplementation(async () => { order.push('delete') })
    const onReplaced = vi.fn()
    await render(<HotelDialogBody spec={SPEC} watch={watched} onReplaced={onReplaced} />)
    await act(async () => button('Not this one?').click())
    await act(async () => button('Watch this instead').click())
    expect(order).toEqual(['create', 'delete', 'create'])
    expect(api.deletePriceWatch).toHaveBeenCalledWith(11, 'tok')
    expect(onReplaced).toHaveBeenCalledWith(next, { spec: ALT.spec })
    expect(container.textContent).toContain('Tracking: Other on Google Hotels')
    expect(container.querySelector('[role="alert"]')).toBeNull()
  })

  it('at the limit, puts the first watch back when the new one fails (M10)', async () => {
    const ALT = { title: 'Other', price: 300, spec: { name: 'Other', property_token: 'o' } }
    const watched = { ...WATCH, alert_mode: 'below_target', target_price: 350, email_enabled: true,
      last_observation: { ...WATCH.last_observation, observed: { alternatives: [ALT] } } }
    const restored = { ...WATCH, id: 13 }
    api.createPriceWatch.mockReset()
      .mockRejectedValueOnce({ response: { status: 409, data: { detail: 'limit' } } })
      .mockRejectedValueOnce(new Error('boom'))
      .mockResolvedValueOnce(restored)
    api.deletePriceWatch.mockReset().mockResolvedValue()
    const onReplaced = vi.fn()
    await render(<HotelDialogBody spec={SPEC} watch={watched} onReplaced={onReplaced} />)
    await act(async () => button('Not this one?').click())
    await act(async () => button('Watch this instead').click())
    expect(api.createPriceWatch).toHaveBeenCalledTimes(3)
    expect(api.createPriceWatch.mock.calls[2][0]).toEqual({
      kind: 'hotel',
      hotel: { name: 'Lumen Hotel', city: 'Lisbon, Portugal', check_in: '2099-12-10', check_out: '2099-12-14', adults: 2, rooms: 1, property_token: 'tok' },
      alert_mode: 'below_target', target_price: 350, email_enabled: true,
    })
    expect(onReplaced).toHaveBeenCalledWith(restored, expect.anything())
    expect(container.querySelector('[role="alert"]').textContent).toContain('still watching the first one')
    expect(container.textContent).toContain('Tracking: Lumen Hotel & The Lisbon Light Show')
  })

  it('says nothing extra when the names agree', async () => {
    await render(<HotelDialogBody spec={SPEC} watch={{ ...WATCH, title: 'Lumen Hotel' }} />)
    expect(container.textContent).not.toContain('Your plan calls it')
  })
})

describe('HotelWatchCard', () => {
  const card = (w) => render(<HotelWatchCard watch={w} onCheck={vi.fn()} onUpdate={vi.fn()} onDelete={vi.fn()} />)

  it('is the registered hotel card', () => {
    expect(cardFor('hotel')).toBe(HotelWatchCard)
  })

  it('shows the property, stay, total and nightly, and a Book link', async () => {
    await card(WATCH)
    const text = container.textContent
    expect(text).toContain('Lumen Hotel & The Lisbon Light Show')
    expect(text).toContain('10–14 Dec · 2 guests · 1 room')
    expect(text).toContain('$398')
    expect(text).toContain('$99.50 a night')
    expect(text).toContain('Total for 4 nights in Lisbon on Google Hotels')
    expect(text).toContain('Your plan called it “Lumen Hotel”.')
    const book = [...container.querySelectorAll('a')].find(a => a.textContent.includes('Book'))
    expect(book.getAttribute('href')).toBe('https://www.lumenhotel.pt/')
    expect(book.getAttribute('rel')).toContain('noopener')
    expect(text).not.toContain('Sold out')
  })

  it('claims taxes are included only when the live look said so', async () => {
    const withTaxes = (t) => ({ ...WATCH, last_observation: { ...WATCH.last_observation, observed: { taxes_included: t } } })
    await card(withTaxes(true))
    expect(container.textContent).toContain('on Google Hotels, taxes and fees included.')
    await card(withTaxes(false))
    expect(container.textContent).toContain('on Google Hotels, before taxes and fees.')
    await card(WATCH)
    expect(container.textContent).not.toContain('taxes')
  })

  it('says “Sold out for your dates” when the last look found no rooms', async () => {
    await card({ ...WATCH, last_observation: { status: 'unavailable', source: 'google_hotels' } })
    expect(container.textContent).toContain('Sold out for your dates')
    expect(container.textContent).toContain('No rooms for your dates right now')
    expect(container.textContent).not.toContain('Not available for your dates right now')
  })

  it('stops offering Book and sold-out once the stay has started', async () => {
    await card({ ...WATCH, status: 'expired', last_observation: { status: 'unavailable' } })
    expect(container.textContent).not.toContain('Sold out')
    expect([...container.querySelectorAll('a')].some(a => a.textContent.includes('Book'))).toBe(false)
  })
})

describe('alertKindFor', () => {
  it('keeps fare and generic copy unchanged', () => {
    for (const kind of ['fare_drop', 'fare_target', 'watch_expired', 'watch_error', 'hotel_drop']) {
      expect(alertKindFor({ kind, data: {} })).toEqual(kindOf(kind))
    }
    expect(alertKindFor({ kind: 'watch_error', data: { reason: 'unavailable' } }).action).toBe('Retry')
    expect(alertKindFor({ kind: 'watch_expired', data: { watch_kind: 'trip' } }).action).toBe('See trip') // trip wording: tripWatch.test.jsx
    expect(alertKindFor(null)).toEqual(kindOf(undefined))
  })

  it('words hotel notices for hotels', () => {
    expect(alertKindFor({ kind: 'hotel_drop', data: { watch_kind: 'hotel' } }).action).toBe('See hotel')
    expect(alertKindFor({ kind: 'hotel_target', data: { watch_kind: 'hotel' } }).action).toBe('See hotel')
    expect(alertKindFor({ kind: 'watch_expired', data: { watch_kind: 'hotel' } }).action).toBe('See hotel')
    // The notice says "Retry whenever you like": the action agrees
    expect(alertKindFor({ kind: 'watch_error', data: { watch_kind: 'hotel', reason: 'unavailable' } }).action).toBe('Retry')
    expect(alertKindFor({ kind: 'watch_error', data: { watch_kind: 'hotel', reason: 'failed' } }).action).toBe('Retry')
  })
})
