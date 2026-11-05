// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { MemoryRouter, Routes, Route, useLocation, useNavigate } from 'react-router-dom'

const auth = { token: 'tok', user: { username: 'u', email: 'u@example.com' }, preferences: {} }
vi.mock('../../context/AuthContext', () => ({ useAuth: () => auth, useOptionalAuth: () => auth }))

const alerts = {
  unread: 0, markRead: vi.fn(), toast: null, dismissToast: vi.fn(), refresh: vi.fn(),
  caps: { serpapi: true, fareWatch: true, email: true },
  watchFor: vi.fn(async () => null), watchVersion: 0, watchesChanged: vi.fn(),
  shouldOfferBrowserAlerts: vi.fn(() => false), answerBrowserAlerts: vi.fn(), markSeen: vi.fn(),
}
vi.mock('../../context/AlertsContext', () => ({ useAlerts: () => alerts }))
vi.mock('../../context/SearchDataContext', () => ({ useSearchData: () => ({ setPendingSearchData: vi.fn() }) }))
vi.mock('../../services/api', () => ({
  listFareWatches: vi.fn(), checkFareWatchNow: vi.fn(), updateFareWatch: vi.fn(), deleteFareWatch: vi.fn(),
  listPriceWatches: vi.fn(), checkPriceWatchNow: vi.fn(), updatePriceWatch: vi.fn(),
  deletePriceWatch: vi.fn(), createPriceWatch: vi.fn(),
}))
vi.mock('../../utils/analytics', () => ({ track: vi.fn() }))

import * as api from '../../services/api'
import AlertsPage from '../../pages/AlertsPage'
import PriceWatchCard from './cards/PriceWatchCard'
import { PRICE_CARDS, cardFor } from './cards'
import { DIALOG_BODIES, dialogBodyFor } from './dialogs'
import GenericPriceBody from './dialogs/GenericPriceBody'
import PriceWatchDialog from './PriceWatchDialog'
import { kindOf } from './alertKinds'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

const FARE = {
  id: 7, status: 'active', origin_label: 'Berlin', destination_label: 'Lisbon', origin_code: 'BER',
  destination_code: 'LIS', departure_date: '2099-12-01', return_date: null, num_travelers: 1,
  baseline_price: 500, last_price: 480, lowest_price: 480, alert_mode: 'any_drop', flexible_days: 0,
  booking_url: 'https://g.co/f', history: [{ price: 500 }, { price: 480 }],
}
const HOTEL = {
  id: 7, kind: 'hotel', status: 'active', title: 'Lumen Hotel', subtitle: 'Lisbon · 10–14 Dec',
  baseline_price: 398, last_price: 352, lowest_price: 352, alert_mode: 'any_drop', target_price: null,
  email_enabled: false, check_count: 2, expires_on: '2099-12-10', link: 'https://hotels.example/lumen',
  last_observation: { status: 'ok', unit_price: 88, source: 'google_hotels', link: 'https://hotels.example/lumen' },
  history: [{ price: 398 }, { price: 352 }],
}
const TRIP = { ...HOTEL, id: 9, kind: 'trip', title: 'Lisbon trip', subtitle: '10–14 Dec', link: null }

let container, root, location
function Where() { location = useLocation(); return null }
const render = async (el, path = '/') => {
  await act(async () => root.render(
    <MemoryRouter initialEntries={[path]}>
      <Routes><Route path="*" element={<>{el}<Where /></>} /></Routes>
    </MemoryRouter>,
  ))
}
const button = (text, scope = document.body) => [...scope.querySelectorAll('button')].find(b => b.textContent.includes(text))
const setValue = (input, value) => {
  Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(input, value)
  input.dispatchEvent(new Event('input', { bubbles: true }))
}

beforeEach(() => {
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
  window.matchMedia = window.matchMedia || (() => ({ matches: false }))
  Element.prototype.scrollIntoView = vi.fn()
  for (const fn of Object.values(api)) fn.mockReset?.()
  api.listFareWatches.mockResolvedValue([FARE])
  api.listPriceWatches.mockResolvedValue([HOTEL, TRIP])
})
afterEach(() => {
  act(() => root.unmount())
  container.remove()
  document.body.innerHTML = ''
  for (const k of Object.keys(PRICE_CARDS)) delete PRICE_CARDS[k]
  for (const k of Object.keys(DIALOG_BODIES)) delete DIALOG_BODIES[k]
})

describe('Alerts page with price watches', () => {
  it('shows filter chips with counts and filters by kind', async () => {
    await render(<AlertsPage />, '/alerts')
    const chips = container.querySelector('[aria-label="Filter watches"]')
    expect(chips.textContent).toContain('All3')
    expect(chips.textContent).toContain('Flights1')
    expect(chips.textContent).toContain('Hotels1')
    expect(chips.textContent).toContain('Trips1')
    expect(container.querySelector('#watch-7')).not.toBeNull()
    expect(container.querySelector('#price-watch-7')).not.toBeNull()
    await act(async () => button('Hotels', chips).click())
    expect(button('Hotels', chips).getAttribute('aria-pressed')).toBe('true')
    expect(container.querySelector('#watch-7')).toBeNull()
    expect(container.querySelector('#price-watch-7').textContent).toContain('Lumen Hotel')
    expect(container.querySelector('#price-watch-9')).toBeNull()
  })

  it('a price-watch deep link highlights that watch and scrolls to it', async () => {
    await render(<AlertsPage />, '/alerts?kind=trip&watch=9')
    const card = container.querySelector('#price-watch-9')
    expect(card.className).toContain('ring-2')
    expect(container.querySelector('#watch-7').className).not.toContain('ring-2') // same id, a fare
  })

  it('Check now on a price watch uses the price API and its wording', async () => {
    api.checkPriceWatchNow.mockResolvedValueOnce({ ...HOTEL, check_status: 'unavailable', notification: null })
    await render(<AlertsPage />, '/alerts?kind=hotel&watch=7')
    await act(async () => button('Check now', container.querySelector('#price-watch-7')).click())
    expect(api.checkPriceWatchNow).toHaveBeenCalledWith(7, 'tok')
    expect(api.checkFareWatchNow).not.toHaveBeenCalled()
    expect(container.querySelector('#price-watch-7').textContent).toContain('isn’t available')
  })

  it('pause and delete go to the price API', async () => {
    api.updatePriceWatch.mockResolvedValueOnce({ ...HOTEL, status: 'paused' })
    await render(<AlertsPage />, '/alerts?kind=hotel&watch=7')
    const card = () => container.querySelector('#price-watch-7')
    await act(async () => button('Pause', card()).click())
    expect(api.updatePriceWatch).toHaveBeenCalledWith(7, { status: 'paused' }, 'tok')
    await act(async () => button('Delete', card()).click())
    await act(async () => button('Delete', card().querySelector('[role="group"]')).click())
    expect(api.deletePriceWatch).toHaveBeenCalledWith(7, 'tok')
    expect(container.querySelector('#price-watch-7')).toBeNull()
    expect(container.querySelector('#watch-7')).not.toBeNull() // the fare with the same id stays
  })

  it('fare watches still show when price watches fail to load', async () => {
    api.listPriceWatches.mockRejectedValueOnce(new Error('offline')).mockResolvedValueOnce([HOTEL])
    await render(<AlertsPage />, '/alerts')
    expect(container.querySelector('#watch-7')).not.toBeNull()
    const note = container.querySelector('[data-testid="price-load-error"]')
    expect(note.textContent).toContain('couldn’t load')
    await act(async () => button('Try again', note).click())
    expect(container.querySelector('#price-watch-7')).not.toBeNull()
  })

  it('renders a registered card for its kind', async () => {
    PRICE_CARDS.hotel = ({ watch }) => <p id={`custom-${watch.id}`}>custom hotel card</p>
    await render(<AlertsPage />, '/alerts')
    expect(container.querySelector('#custom-7').textContent).toBe('custom hotel card')
    expect(container.querySelector('#price-watch-9')).not.toBeNull() // trip: default card
  })
})

describe('Alerts page — fix round 1', () => {
  it('a deep link reaches a watch hidden by the current filter', async () => {
    let navigateTo
    function Nav() { navigateTo = useNavigate(); return null }
    await render(<><AlertsPage /><Nav /></>, '/alerts')
    const chips = () => container.querySelector('[aria-label="Filter watches"]')
    await act(async () => button('Hotels', chips()).click())
    expect(container.querySelector('#watch-7')).toBeNull()
    await act(async () => navigateTo('/alerts?watch=7'))
    expect(container.querySelector('#watch-7').className).toContain('ring-2')
    expect(button('All', chips()).getAttribute('aria-pressed')).toBe('true')
  })

  it('price watches still show when fare watches fail to load', async () => {
    api.listFareWatches.mockRejectedValueOnce(new Error('offline')).mockResolvedValueOnce([FARE])
    await render(<AlertsPage />, '/alerts')
    expect(container.querySelector('[role="alert"]').textContent).toContain('Couldn’t load your watched flights')
    expect(container.querySelector('#price-watch-7')).not.toBeNull()
    expect(container.textContent).not.toContain('Nothing watched yet')
    await act(async () => button('Try again', container.querySelector('[role="alert"]')).click())
    expect(container.querySelector('#watch-7')).not.toBeNull()
  })

  it('a price-watch deep link waits for a failed price list to load', async () => {
    api.listPriceWatches.mockRejectedValueOnce(new Error('offline')).mockResolvedValueOnce([HOTEL, TRIP])
    await render(<AlertsPage />, '/alerts?kind=trip&watch=9')
    await act(async () => button('Try again', container.querySelector('[data-testid="price-load-error"]')).click())
    expect(container.querySelector('#price-watch-9').className).toContain('ring-2')
  })

  it('has a generic empty state', async () => {
    api.listFareWatches.mockResolvedValue([])
    api.listPriceWatches.mockResolvedValue([])
    await render(<AlertsPage />, '/alerts')
    const t = container.textContent
    expect(t).toContain('Nothing watched yet')
    for (const word of ['flight', 'hotel', 'activit', 'trip']) expect(t.toLowerCase()).toContain(word)
  })

  it('an empty tab says how to watch that kind', async () => {
    await render(<AlertsPage />, '/alerts')
    await act(async () => button('Activities', container.querySelector('[aria-label="Filter watches"]')).click())
    expect(container.textContent).toContain('No activities watched yet')
  })

  it('chips have spoken names and the filter result is announced', async () => {
    await render(<AlertsPage />, '/alerts')
    const chips = container.querySelector('[aria-label="Filter watches"]')
    expect(button('Hotels', chips).getAttribute('aria-label')).toBe('Hotels, 1')
    await act(async () => button('Hotels', chips).click())
    expect(container.querySelector('[aria-live="polite"][data-testid="filter-status"]').textContent)
      .toBe('Showing 1 hotel watch')
  })

  it('shows a non-USD watch in its own currency, with cents', async () => {
    const eur = { ...HOTEL, id: 11, kind: 'activity', currency: 'EUR', baseline_price: 11.63, last_price: 9.9,
      lowest_price: 9.9, target_price: 9, alert_mode: 'below_target',
      last_observation: { status: 'ok', unit_price: 9.9 }, history: [{ price: 11.63 }, { price: 9.9 }] }
    api.listPriceWatches.mockResolvedValue([eur])
    await render(<AlertsPage />, '/alerts')
    const card = container.querySelector('#price-watch-11').textContent
    expect(card).toContain('€9.90')
    expect(card).toContain('€1.73 less than when you started')
    expect(card).toContain('€9 or less')
    expect(card).not.toContain('$')
  })
})

describe('PriceWatchCard', () => {
  const props = (over = {}) => ({
    watch: HOTEL, onCheck: vi.fn(), onUpdate: vi.fn(async () => true), onDelete: vi.fn(), onOpen: vi.fn(), ...over,
  })

  it('shows the price, its change, the unit price and the listing link', async () => {
    await render(<PriceWatchCard {...props()} />)
    const t = container.textContent
    expect(t).toContain('Lumen Hotel')
    expect(t).toContain('Lisbon · 10–14 Dec')
    expect(t).toContain('$352')
    expect(t).toContain('$46 less than when you started')
    expect(t).toContain('$88')
    const link = container.querySelector('a[href="https://hotels.example/lumen"]')
    expect(link.getAttribute('target')).toBe('_blank')
  })

  it('says when it is not available for the dates', async () => {
    await render(<PriceWatchCard {...props({ watch: { ...HOTEL, last_observation: { status: 'unavailable' } } })} />)
    expect(container.textContent).toContain('Not available for your dates right now')
  })

  it('offers Retry when checks are on hold', async () => {
    const p = props({ watch: { ...HOTEL, status: 'error', problem: 'Live prices aren’t available right now.' } })
    await render(<PriceWatchCard {...p} />)
    expect(container.textContent).toContain('on hold')
    await act(async () => button('Retry').click())
    expect(p.onUpdate).toHaveBeenCalledWith({ status: 'active' })
  })

  it('edits the alert mode and target', async () => {
    const p = props()
    await render(<PriceWatchCard {...p} />)
    await act(async () => button('Edit').click())
    setValue(container.querySelector('input[aria-label="Target price in US dollars"]'), '300')
    await act(async () => container.querySelector('form').dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })))
    expect(p.onUpdate).toHaveBeenCalledWith({ alert_mode: 'below_target', target_price: 300, email_enabled: false })
  })

  it('renders kind details passed in', async () => {
    await render(<PriceWatchCard {...props()} Details={({ watch }) => <span>details for {watch.title}</span>} />)
    expect(container.textContent).toContain('details for Lumen Hotel')
  })

  it('past watches have no live actions', async () => {
    await render(<PriceWatchCard {...props({ watch: { ...HOTEL, status: 'expired' } })} />)
    expect(button('Check now')).toBeUndefined()
    expect(button('Delete')).toBeDefined()
  })
})

describe('registries', () => {
  it('fall back to the generic card and dialog body', () => {
    expect(cardFor('hotel')).toBe(PriceWatchCard)
    expect(dialogBodyFor('hotel')).toBe(GenericPriceBody)
    const Mine = () => null
    DIALOG_BODIES.hotel = Mine
    expect(dialogBodyFor('hotel')).toBe(Mine)
  })

  it('every price alert kind has an icon and action', () => {
    for (const k of ['hotel', 'activity', 'trip']) {
      for (const s of ['_drop', '_target']) {
        expect(kindOf(`${k}${s}`)).not.toBe(kindOf('watch_expired'))
      }
    }
  })
})

describe('PriceWatchDialog', () => {
  const open = async (over = {}) => {
    const p = { kind: 'hotel', spec: { name: 'Lumen Hotel', city: 'Lisbon' }, preview: { title: 'Lumen Hotel', subtitle: 'Lisbon', price: 400 }, onClose: vi.fn(), onWatched: vi.fn(), ...over }
    await render(<PriceWatchDialog {...p} />)
    return p
  }
  const submit = async () => {
    await act(async () => document.querySelector('[role="dialog"] form').dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })))
  }

  it('creates a watch with the spec under its kind and confirms it', async () => {
    api.createPriceWatch.mockResolvedValueOnce({ ...HOTEL, already_watching: false })
    const p = await open()
    const dialog = document.querySelector('[role="dialog"]')
    expect(dialog.getAttribute('aria-modal')).toBe('true')
    expect(dialog.textContent).toContain('Watch this hotel')
    expect(dialog.textContent).toContain('$400')
    await submit()
    expect(api.createPriceWatch).toHaveBeenCalledWith({
      kind: 'hotel', hotel: { name: 'Lumen Hotel', city: 'Lisbon' },
      alert_mode: 'any_drop', target_price: null, email_enabled: false,
    }, 'tok')
    expect(document.querySelector('[role="status"]').textContent).toContain('$398')
    expect(p.onWatched).toHaveBeenCalled()
    expect(alerts.watchesChanged).toHaveBeenCalled()
    const see = [...document.querySelectorAll('a')].find(a => a.textContent.includes('See your alerts'))
    expect(see.getAttribute('href')).toBe('/alerts?kind=hotel&watch=7')
  })

  it('after picking a suggestion, reports and shows what is really watched', async () => {
    const lisboa = { ...HOTEL, id: 8, title: 'Lumen Lisboa', subtitle: 'Baixa · 10–14 Dec' }
    api.createPriceWatch
      .mockRejectedValueOnce({ response: { status: 422, data: {
        detail: 'No live price.', code: 'no_live_price', message: 'No live price.',
        suggestions: [{ title: 'Lumen Lisboa', price: 380, currency: 'EUR', spec: { name: 'Lumen Lisboa' } }],
        estimate: { price: 420, currency: 'EUR' },
      } } })
      .mockResolvedValueOnce(lisboa)
    DIALOG_BODIES.hotel = ({ spec, watch }) => <p data-testid="body">{watch ? `tracking ${spec.name}` : spec.name}</p>
    const p = await open()
    await submit()
    const dialog = document.querySelector('[role="dialog"]')
    expect(dialog.textContent).toContain('€380')
    expect(dialog.textContent).toContain('€420')
    expect(button('Start watching', dialog)).toBeUndefined() // no re-send of the failed spec
    await act(async () => button('Watch this instead', dialog).click())
    expect(p.onWatched).toHaveBeenCalledWith(lisboa, { spec: { name: 'Lumen Lisboa' }, viaSuggestion: true })
    expect(dialog.textContent).toContain('Lumen Lisboa · Baixa · 10–14 Dec')
    expect(dialog.textContent).not.toContain('Lumen Hotel · Lisbon')
    expect(document.querySelector('[data-testid="body"]').textContent).toBe('tracking Lumen Lisboa')
  })

  it('reports the original spec when it matched directly', async () => {
    api.createPriceWatch.mockResolvedValueOnce(HOTEL)
    const p = await open()
    await submit()
    expect(p.onWatched).toHaveBeenCalledWith(HOTEL, { spec: { name: 'Lumen Hotel', city: 'Lisbon' }, viaSuggestion: false })
  })

  it('already watching: says so and offers no browser alerts', async () => {
    alerts.shouldOfferBrowserAlerts.mockReturnValue(true)
    api.createPriceWatch.mockResolvedValueOnce({ ...HOTEL, already_watching: true })
    await open()
    await submit()
    expect(document.querySelector('[role="dialog"]').textContent).toContain('You’re already watching this hotel')
    expect(button('Allow browser alerts')).toBeUndefined()
    alerts.shouldOfferBrowserAlerts.mockReturnValue(false)
  })

  it('never shows a made-up price when the watch has none yet', async () => {
    api.createPriceWatch.mockResolvedValueOnce({ ...HOTEL, baseline_price: null, last_price: null })
    await open()
    await submit()
    const status = document.querySelector('[role="status"]').textContent
    expect(status).not.toContain('$0')
    expect(status).toContain('shortly')
  })

  it('labels the target with the currency and passes a unit label to the body', async () => {
    await open({ preview: { title: 'Tour', price: 24, currency: 'EUR' }, kind: 'activity', unitLabel: 'per person' })
    expect(document.body.textContent).toContain('€24')
    expect(document.body.textContent).toContain('per person')
    await act(async () => document.querySelector('input[value="below_target"]').click())
    expect(document.querySelector('input[aria-label="Target price in EUR"]')).not.toBeNull()
  })

  it('offers live suggestions when there is no live price', async () => {
    api.createPriceWatch
      .mockRejectedValueOnce({ response: { status: 422, data: {
        detail: 'We couldn’t find live prices for this hotel on Google Hotels.', code: 'no_live_price',
        message: 'We couldn’t find live prices for this hotel on Google Hotels.',
        suggestions: [{ title: 'Lumen Lisboa', subtitle: 'Baixa', price: 380, spec: { name: 'Lumen Lisboa', city: 'Lisbon' } }],
        estimate: { price: 420 },
      } } })
      .mockResolvedValueOnce({ ...HOTEL, title: 'Lumen Lisboa' })
    await open()
    await submit()
    const dialog = document.querySelector('[role="dialog"]')
    expect(dialog.textContent).toContain('couldn’t find live prices')
    expect(dialog.textContent).toContain('Lumen Lisboa')
    expect(dialog.textContent).toContain('$380')
    expect(dialog.textContent).toContain('estimate')
    await act(async () => button('Watch this instead', dialog).click())
    expect(api.createPriceWatch).toHaveBeenLastCalledWith(expect.objectContaining({
      kind: 'hotel', hotel: { name: 'Lumen Lisboa', city: 'Lisbon' },
    }), 'tok')
    expect(document.querySelector('[role="status"]')).not.toBeNull()
  })

  it('does not re-send the failed spec when the form is submitted after no live price', async () => {
    api.createPriceWatch.mockRejectedValueOnce({ response: { status: 422, data: {
      detail: 'No live price.', code: 'no_live_price', message: 'No live price.',
      suggestions: [{ title: 'Lumen Lisboa', price: 380, spec: { name: 'Lumen Lisboa', city: 'Lisbon' } }],
    } } })
    await open()
    await submit()
    await submit()
    expect(api.createPriceWatch).toHaveBeenCalledTimes(1)
  })

  it('shows other errors as they come', async () => {
    api.createPriceWatch.mockRejectedValueOnce({ response: { status: 409, data: { detail: 'You already have 10 active watches — pause or remove one to watch another.' } } })
    await open()
    await submit()
    expect(document.querySelector('[role="alert"]').textContent).toContain('10 active watches')
  })

  it('target mode sends the target', async () => {
    api.createPriceWatch.mockResolvedValueOnce(HOTEL)
    await open()
    await act(async () => document.querySelector('input[value="below_target"]').click())
    setValue(document.querySelector('input[aria-label="Target price in US dollars"]'), '350')
    await submit()
    expect(api.createPriceWatch).toHaveBeenCalledWith(expect.objectContaining({ alert_mode: 'below_target', target_price: 350 }), 'tok')
  })

  it('uses the registered body for its kind', async () => {
    DIALOG_BODIES.hotel = ({ spec, watch }) => <p>{watch ? `tracking ${watch.title}` : `matching ${spec.name}`}</p>
    api.createPriceWatch.mockResolvedValueOnce(HOTEL)
    await open()
    expect(document.body.textContent).toContain('matching Lumen Hotel')
    await submit()
    expect(document.body.textContent).toContain('tracking Lumen Hotel')
  })

  it('Escape closes', async () => {
    const p = await open()
    await act(async () => document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true })))
    expect(p.onClose).toHaveBeenCalled()
  })
})
