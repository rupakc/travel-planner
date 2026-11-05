// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { MemoryRouter, Routes, Route, useLocation } from 'react-router-dom'

const auth = { token: 'tok', user: { username: 'u', email: 'u@example.com' }, preferences: {} }
vi.mock('../../context/AuthContext', () => ({ useAuth: () => auth, useOptionalAuth: () => auth }))

let watched = null
const alerts = {
  caps: { serpapi: true, fareWatch: true, email: true },
  watchVersion: 0, watchesChanged: vi.fn(),
  priceWatchFor: vi.fn(async () => watched),
  shouldOfferBrowserAlerts: vi.fn(() => false), answerBrowserAlerts: vi.fn(),
}
vi.mock('../../context/AlertsContext', async () => {
  const { useEffect, useState } = await import('react')
  return {
    useAlerts: () => alerts,
    usePriceWatchFor: (kind, spec) => {
      const [w, setW] = useState(null)
      useEffect(() => { alerts.priceWatchFor(kind, spec).then(setW) }, [])
      return [w, setW]
    },
  }
})
vi.mock('../../services/api', () => ({ createPriceWatch: vi.fn() }))
vi.mock('../../utils/analytics', () => ({ track: vi.fn() }))

import * as api from '../../services/api'
import WatchActivityButton from './WatchActivityButton'
import { ActivityTripContext } from './activityTripContext'
import ActivityDialogBody from './dialogs/ActivityDialogBody'
import ActivityWatchCard from './cards/ActivityWatchCard'
import { PRICE_CARDS, cardFor } from './cards'
import { DIALOG_BODIES, dialogBodyFor } from './dialogs'
import { ALERT_KINDS, alertKindFor, kindOf, keepDeltaTogether } from './alertKinds'
import { ownWatch } from '../../utils/activityWatch'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

const WALK = 'Small Group Walking Tour of Belém'
const URL = 'https://www.getyourguide.com/lisbon-l42/small-group-walking-tour-of-belem-t78184'
const WATCH = {
  id: 12, kind: 'activity', status: 'active', title: WALK,
  subtitle: 'GetYourGuide · from $33.46 per person · 2 travellers', currency: 'USD',
  subject: {
    name: 'Belém walking tour', city: 'Lisbon', listing_url: URL, listing_title: WALK,
    provider: 'getyourguide', travellers: 2, currency: 'USD', date: null,
  },
  baseline_price: 66.92, last_price: 58, lowest_price: 58, alert_mode: 'any_drop', target_price: null,
  email_enabled: false, check_count: 2, expires_on: '2099-05-01', link: URL,
  last_observation: {
    status: 'ok', unit_price: 29, source: 'getyourguide_via_google', link: URL,
    observed: { rating: 4.9, reviews: 80, source: 'getyourguide_via_google' },
  },
  history: [{ price: 66.92 }, { price: 58 }],
}
const ACTIVITY = { name: 'Belém walking tour', price_usd: 30 }
const TRIP = {
  searchData: { destination: 'Lisbon, Portugal', num_travelers: 2 },
  itinerary: { days: [{ date: '2099-04-20', slots: [{ activity: 'Belém walking tour' }] }] },
}

let container, root, location
function Where() { location = useLocation(); return null }
const render = async (el, path = '/results') => {
  await act(async () => root.render(
    <MemoryRouter initialEntries={[path]}>
      <ActivityTripContext.Provider value={TRIP}>
        <Routes><Route path="*" element={<>{el}<Where /></>} /></Routes>
      </ActivityTripContext.Provider>
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
  watched = null
  auth.token = 'tok'
  alerts.caps = { serpapi: true, fareWatch: true, email: true }
  alerts.watchesChanged.mockReset()
  alerts.priceWatchFor.mockClear()
  api.createPriceWatch.mockReset()
})
afterEach(() => {
  act(() => root.unmount())
  container.remove()
  document.body.innerHTML = ''
})

describe('WatchActivityButton', () => {
  it('is hidden without live prices', async () => {
    alerts.caps = { serpapi: false, fareWatch: false, email: false }
    await render(<WatchActivityButton activity={ACTIVITY} />)
    expect(container.textContent).toBe('')
  })

  it('signed out, it leads to sign-in and back', async () => {
    auth.token = null
    await render(<WatchActivityButton activity={ACTIVITY} />, '/results?x=1')
    const link = container.querySelector('a')
    expect(link.textContent).toContain('Watch price')
    await act(async () => link.click())
    expect(location.pathname).toBe('/login')
    expect(new URLSearchParams(location.search).get('next')).toBe('/results?x=1')
  })

  it('looks up the watch with the search’s travellers, city, itinerary day and estimate', async () => {
    await render(<WatchActivityButton activity={ACTIVITY} />)
    expect(alerts.priceWatchFor).toHaveBeenCalledWith('activity', {
      name: 'Belém walking tour', city: 'Lisbon', travellers: 2, date: '2099-04-20', estimate_price: 30,
    })
  })

  it('opens the dialog and creates an activity watch', async () => {
    api.createPriceWatch.mockResolvedValueOnce({ ...WATCH, already_watching: false })
    await render(<WatchActivityButton activity={ACTIVITY} />)
    await act(async () => button('Watch price').click())
    const dialog = document.querySelector('[role="dialog"]')
    expect(dialog.textContent).toContain('Watch this activity')
    expect(dialog.textContent).toContain('GetYourGuide and Viator')
    expect(dialog.textContent).toContain('estimate')
    await act(async () => button('Start watching', dialog).click())
    expect(api.createPriceWatch).toHaveBeenCalledWith(expect.objectContaining({
      kind: 'activity', activity: expect.objectContaining({ name: 'Belém walking tour', travellers: 2 }),
    }), 'tok')
    expect(document.querySelector('[role="dialog"]').textContent).toContain(WALK)
    await act(async () => button('Done').click())
    expect(button('Watching').textContent).toContain('Watching · from $29 pp')
  })

  it('once watched it reads per person and opens the Alerts page', async () => {
    watched = { ...WATCH, currency: 'EUR', last_observation: { ...WATCH.last_observation, unit_price: 11.63 } }
    await render(<WatchActivityButton activity={ACTIVITY} />)
    const b = button('Watching')
    expect(b.textContent).toContain('Watching · from €11.63 pp')
    expect(b.getAttribute('aria-label')).toContain('open your alerts')
    await act(async () => b.click())
    expect(location.pathname + location.search).toBe('/alerts?kind=activity&watch=12')
  })

  it('marks its own subject only when the watch wasn’t a picked suggestion', () => {
    expect(ownWatch(WATCH, { spec: {}, viaSuggestion: false })).toBe(WATCH)
    expect(ownWatch(WATCH)).toBe(WATCH) // older dialogs pass no details
    expect(ownWatch(WATCH, { spec: {}, viaSuggestion: true })).toBe(null)
  })
})

describe('target currency (fix round 1)', () => {
  it('asks again in the listing currency when it differs, with the same spec', async () => {
    api.createPriceWatch
      .mockRejectedValueOnce({ response: { status: 422, data: {
        code: 'target_currency_mismatch', currency: 'EUR', price: 61, unit_price: 30.5,
        message: 'This is priced in EUR (now €61). Enter your target in EUR.', detail: 'x',
      } } })
      .mockResolvedValueOnce({ ...WATCH, currency: 'EUR', already_watching: false })
    await render(<WatchActivityButton activity={ACTIVITY} />)
    await act(async () => button('Watch price').click())
    await act(async () => document.querySelector('input[value="below_target"]').click())
    const input = () => document.querySelector('input[aria-label^="Target price in"]')
    expect(input().getAttribute('aria-label')).toBe('Target price in US dollars')
    setValue(input(), '50')
    await act(async () => button('Start watching').click())
    expect(api.createPriceWatch.mock.calls[0][0]).toMatchObject({ target_price: 50, target_currency: 'USD' })
    expect(input().getAttribute('aria-label')).toBe('Target price in EUR')
    expect(input().value).toBe('')
    expect(input().getAttribute('placeholder')).toBeTruthy()
    expect(document.body.textContent).toContain('priced in EUR')
    setValue(input(), '55')
    await act(async () => button('Start watching').click())
    const second = api.createPriceWatch.mock.calls[1][0]
    expect(second).toMatchObject({ target_price: 55, target_currency: 'EUR' })
    expect(second.activity).toEqual(api.createPriceWatch.mock.calls[0][0].activity)
    expect(document.querySelector('[role="dialog"]').textContent).toContain('Watching this activity')
  })

  it('after a currency mismatch on a picked suggestion, the body shows the pick', async () => {
    const PICK = 'https://www.getyourguide.com/lisbon-l42/jeronimos-t1374987'
    api.createPriceWatch
      .mockRejectedValueOnce({ response: { status: 422, data: {
        code: 'no_live_price', message: 'none', suggestions: [{ title: 'Jerónimos ticket', price: 22.87, currency: 'EUR',
          link: PICK, spec: { name: 'Belém walking tour', city: 'Lisbon', travellers: 2, listing_url: PICK } }],
      } } })
      .mockRejectedValueOnce({ response: { status: 422, data: {
        code: 'target_currency_mismatch', currency: 'EUR', price: 45.74, unit_price: 22.87, message: 'This is priced in EUR.',
      } } })
    await render(<WatchActivityButton activity={ACTIVITY} />)
    await act(async () => button('Watch price').click())
    await act(async () => document.querySelector('input[value="below_target"]').click())
    setValue(document.querySelector('input[aria-label^="Target price in"]'), '50')
    await act(async () => button('Start watching').click())
    await act(async () => button('Watch this instead').click())
    const dialog = document.querySelector('[role="dialog"]')
    expect(dialog.textContent).toContain('the listing you picked')
    expect(dialog.querySelector(`a[href="${PICK}"]`)).not.toBeNull()
  })

  it('labels per-person estimates and suggestion prices', async () => {
    api.createPriceWatch.mockRejectedValueOnce({ response: { status: 422, data: {
      code: 'no_live_price', message: 'none', estimate: { price: 30, currency: 'USD', label: 'per person', source: 'ai_estimate' },
      suggestions: [{ title: 'Jerónimos ticket', price: 22.87, currency: 'USD', price_label: 'per person', spec: { name: 'x' } }],
    } } })
    await render(<WatchActivityButton activity={ACTIVITY} />)
    await act(async () => button('Watch price').click())
    await act(async () => button('Start watching').click())
    const alert = document.querySelector('[role="alert"]').textContent
    expect(alert).toContain('$30 per person')
    expect(alert).toContain('$22.87per person')
  })
})

describe('ActivityDialogBody', () => {
  it('before matching: what we will look for, with the AI estimate labelled', async () => {
    await render(<ActivityDialogBody kind="activity" spec={{ name: 'Belém walking tour', city: 'Lisbon', travellers: 2, date: '2099-04-20', estimate_price: 30 }} preview={{}} watch={null} />)
    const t = container.textContent
    expect(t).toContain('Belém walking tour')
    expect(t).toContain('GetYourGuide and Viator')
    expect(t).toContain('2 travellers')
    expect(t).toContain('20 Apr')
    expect(t).toContain('$30 per person')
    expect(t).toMatch(/AI estimate/)
  })

  it('after matching: provider, listing, rating, per person × travellers, link and honesty note', async () => {
    await render(<ActivityDialogBody kind="activity" spec={WATCH.subject} preview={{}} watch={WATCH} />)
    const t = container.textContent
    expect(t).toContain('GetYourGuide')
    expect(t).toContain(WALK)
    expect(t).toContain('4.9')
    expect(t).toContain('80 reviews')
    expect(t).toContain('from $29 per person')
    expect(t).toContain('× 2 travellers')
    expect(t).toContain('$58')
    expect(t).toContain('Price as shown in Google results for GetYourGuide')
    expect(t).toContain('closest listing we found for “Belém walking tour”')
    const link = container.querySelector(`a[href="${URL}"]`)
    expect(link.getAttribute('target')).toBe('_blank')
    expect(link.getAttribute('rel')).toContain('noopener')
    expect(container.querySelector('img')).toBeNull() // provider as text, no logos
  })

  it('uses the created watch’s currency, not the page preview’s (a picked suggestion may differ)', async () => {
    const w = { ...WATCH, currency: 'EUR', subject: { ...WATCH.subject, name: WALK, currency: 'EUR' } }
    await render(<ActivityDialogBody kind="activity" spec={w.subject} preview={{ currency: 'USD', price: 60 }} watch={w} />)
    expect(container.textContent).not.toContain('$')
    expect(container.textContent).not.toContain('closest listing')
    expect(container.textContent).toContain('€29')
    expect(container.textContent).toContain('in EUR')
  })
})

describe('ActivityWatchCard', () => {
  const props = { onCheck: vi.fn(), onUpdate: vi.fn(), onDelete: vi.fn(), onOpen: vi.fn() }

  it('shows the listing, provider, per person and total, Open listing and a sparkline', async () => {
    await render(<ActivityWatchCard watch={WATCH} {...props} />)
    const t = container.textContent
    expect(t).toContain(WALK)
    expect(t).toContain('GetYourGuide')
    expect(t).toContain('from $29 per person')
    expect(t).toContain('× 2 travellers = $58')
    const open = [...container.querySelectorAll('a')].find(a => a.textContent.includes('Open listing'))
    expect(open.getAttribute('href')).toBe(URL)
    expect(container.querySelector('svg[role="img"], svg[aria-label]')).not.toBeNull()
  })

  it('says “Not currently listed” when the last look found nothing', async () => {
    const w = { ...WATCH, last_observation: { status: 'unavailable', observed: { reason: 'not_found' } } }
    await render(<ActivityWatchCard watch={w} {...props} />)
    expect(container.textContent).toContain('Not currently listed')
    expect(container.textContent).not.toContain('for your dates')
  })

  it('shows money in the watch’s currency', async () => {
    const w = { ...WATCH, currency: 'EUR', subtitle: 'GetYourGuide · from €33.46 per person · 2 travellers', subject: { ...WATCH.subject, currency: 'EUR' } }
    await render(<ActivityWatchCard watch={w} {...props} />)
    expect(container.textContent).toContain('from €29 per person')
    expect(container.textContent).toContain('€58')
    expect(container.textContent).not.toContain('$')
  })

  it('explains a currency change instead of comparing', async () => {
    const w = { ...WATCH, last_observation: { status: 'unavailable', observed: { reason: 'currency_changed', seen_currency: 'EUR' } } }
    await render(<ActivityWatchCard watch={w} {...props} />)
    expect(container.textContent).toContain('EUR')
  })
})

describe('registries and alert copy', () => {
  it('registers the activity card and dialog body', () => {
    expect(PRICE_CARDS.activity).toBe(ActivityWatchCard)
    expect(cardFor('activity')).toBe(ActivityWatchCard)
    expect(DIALOG_BODIES.activity).toBe(ActivityDialogBody)
    expect(dialogBodyFor('activity')).toBe(ActivityDialogBody)
  })

  it('activity notices get the activity icon; fare and hotel copy are unchanged', () => {
    const n = (kind, data) => ({ kind, data })
    expect(alertKindFor(n('watch_error', { watch_kind: 'activity' })).Icon).toBe(ALERT_KINDS.activity_drop.Icon)
    expect(alertKindFor(n('watch_expired', { watch_kind: 'activity' })).Icon).toBe(ALERT_KINDS.activity_drop.Icon)
    expect(alertKindFor(n('watch_error', { watch_kind: 'activity' })).action).toBe(ALERT_KINDS.watch_error.action)
    expect(alertKindFor(n('watch_error'))).toBe(ALERT_KINDS.watch_error)
    expect(alertKindFor(n('watch_error', {}))).toBe(ALERT_KINDS.watch_error)
    expect(alertKindFor(n('fare_drop', { watch_kind: 'activity' }))).toBe(ALERT_KINDS.fare_drop)
    expect(alertKindFor(n('watch_expired', { watch_kind: 'hotel' })).action).toBe('See hotel')
    expect(kindOf('watch_error')).toBe(ALERT_KINDS.watch_error)
  })

  it('keeps any currency’s delta together', () => {
    expect(keepDeltaTogether('now from €9.90 per person (−€1.73)')).toBe('now from €9.90 per person (−⁠€1.73)')
    expect(keepDeltaTogether('(−A$2.10)')).toBe('(−⁠A$2.10)')
    expect(keepDeltaTogether('Berlin → Lisbon dropped to $150 (−$70)')).toBe('Berlin → Lisbon dropped to $150 (−⁠$70)')
    expect(keepDeltaTogether('Day-trip')).toBe('Day-trip')
  })
})
