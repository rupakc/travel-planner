// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { MemoryRouter, Routes, Route, useLocation } from 'react-router-dom'

const auth = { token: 'tok', user: { username: 'u', email: null }, preferences: { nationality: 'German', interests: ['food'] } }
vi.mock('../../context/AuthContext', () => ({ useAuth: () => auth, useOptionalAuth: () => auth }))

const alerts = {
  unread: 0, markRead: vi.fn(), toast: null, dismissToast: vi.fn(), refresh: vi.fn(),
  caps: { serpapi: true, fareWatch: true, email: true },
  watchFor: vi.fn(async () => null), watchVersion: 0, watchesChanged: vi.fn(),
  shouldOfferBrowserAlerts: vi.fn(() => true), answerBrowserAlerts: vi.fn(),
  markSeen: vi.fn(),
}
vi.mock('../../context/AlertsContext', async () => {
  const { useState, useEffect } = await import('react')
  return {
    useAlerts: () => alerts,
    useWatchFor: (trip) => {
      const [w, setW] = useState(null)
      useEffect(() => { alerts.watchFor(trip).then(setW) }, [])
      return [w, setW]
    },
  }
})

const pending = vi.fn()
vi.mock('../../context/SearchDataContext', () => ({ useSearchData: () => ({ setPendingSearchData: pending }) }))

vi.mock('../../services/api', () => ({
  createFareWatch: vi.fn(),
  listNotifications: vi.fn(),
  listFareWatches: vi.fn(),
  checkFareWatchNow: vi.fn(),
  updateFareWatch: vi.fn(),
  deleteFareWatch: vi.fn(),
}))
vi.mock('../../utils/analytics', () => ({ track: vi.fn() }))

import * as api from '../../services/api'
import WatchFareButton from './WatchFareButton'
import NotificationBell from './NotificationBell'
import AlertToast from './AlertToast'
import WatchCard from './WatchCard'
import Sparkline from './Sparkline'
import AlertsPage from '../../pages/AlertsPage'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

const TRIP = { origin: 'Berlin', destination: 'Lisbon', departure_date: '2099-12-01', return_date: '2099-12-08', num_travelers: 2, destinations: null }
const WATCH = {
  id: 7, status: 'active', origin_label: 'Berlin, Germany', destination_label: 'Lisbon, Portugal',
  origin_code: 'BER', destination_code: 'LIS', departure_date: '2099-12-01', return_date: '2099-12-08',
  num_travelers: 2, baseline_price: 500, last_price: 454, lowest_price: 454, check_count: 2,
  alert_mode: 'any_drop', target_price: null, flexible_days: 0, email_enabled: false,
  google_price_level: 'low', booking_url: 'https://www.google.com/flights#flt=BER.LIS',
  last_checked_at: new Date().toISOString(), next_check_at: null,
  history: [{ price: 500 }, { price: 454 }],
}

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
  Object.assign(alerts, { unread: 0, toast: null })
  alerts.caps = { serpapi: true, fareWatch: true, email: true }
  alerts.watchFor.mockReset().mockResolvedValue(null)
  vi.clearAllMocks()
  alerts.watchFor.mockResolvedValue(null)
  alerts.shouldOfferBrowserAlerts.mockReturnValue(true)
  auth.user = { username: 'u', email: null }
})
afterEach(() => {
  act(() => root.unmount())
  container.remove()
  document.body.innerHTML = ''
})

// ── Watch button + dialog ─────────────────────────────────────────────────────

describe('WatchFareButton', () => {
  it('renders nothing without live fares, for multi-city or departed trips', async () => {
    alerts.caps = { ...alerts.caps, fareWatch: false }
    await render(<WatchFareButton trip={TRIP} />)
    expect(container.textContent).toBe('')
    alerts.caps = { ...alerts.caps, fareWatch: true }
    await render(<WatchFareButton trip={{ ...TRIP, destinations: ['Paris', 'Rome'] }} />)
    expect(container.textContent).toBe('')
    await render(<WatchFareButton trip={{ ...TRIP, departure_date: '2000-01-01' }} />)
    expect(container.textContent).toBe('')
  })

  it('shows “Watching · $454” for a watched trip and opens its alert', async () => {
    alerts.watchFor.mockResolvedValue(WATCH)
    await render(<WatchFareButton trip={TRIP} />)
    const b = button('Watching')
    expect(b.textContent).toContain('Watching · $454')
    await act(async () => b.click())
    expect(location.pathname + location.search).toBe('/alerts?watch=7')
  })

  it('creates a watch with a validated target and confirms it', async () => {
    api.createFareWatch.mockResolvedValue({ ...WATCH, alert_mode: 'below_target', target_price: 450, baseline_price: 480, already_watching: false })
    await render(<WatchFareButton trip={TRIP} price={480} insights={{ typical_price_range: [452, 620] }} />)
    await act(async () => button('Watch fare').click())
    const dialog = document.querySelector('[role="dialog"]')
    expect(dialog.textContent).toContain('$480')
    expect(dialog.textContent).toContain('Today is within the usual $452–$620')
    // email offered but disabled without an address
    const emailBox = [...dialog.querySelectorAll('input[type="checkbox"]')][1]
    expect(emailBox.disabled).toBe(true)
    expect(dialog.textContent).toContain('Preferences')

    await act(async () => dialog.querySelector('input[value="below_target"]').click())
    const target = dialog.querySelector('input[aria-label="Target price in US dollars"]')
    expect(target.value).toBe('450')
    act(() => setValue(target, 'abc'))
    expect(button('Start watching', dialog).disabled).toBe(true)
    act(() => setValue(target, '450'))
    await act(async () => button('Start watching', dialog).click())

    expect(api.createFareWatch).toHaveBeenCalledWith({
      ...TRIP, alert_mode: 'below_target', target_price: 450, flexible_days: 0, email_enabled: false,
    }, 'tok')
    expect(alerts.watchesChanged).toHaveBeenCalled()
    const done = document.querySelector('[role="dialog"]')
    expect(done.textContent).toContain('Watching this fare')
    expect(done.textContent).toContain('$480')
    expect(done.textContent).toContain('Get a heads-up on this device too?')
    await act(async () => button('Not now', done).click())
    expect(alerts.answerBrowserAlerts).toHaveBeenCalledWith(false)
    expect(document.body.textContent).not.toContain('Get a heads-up')
  })

  it.each([
    [{ already_below_target: true, alert_mode: 'below_target', target_price: 500 }, 'Already below your target — we’ll tell you if it drops further.'],
    [{ already_low: true }, 'Google already rates this as a low price — we’ll tell you if it drops further.'],
  ])('says when the fare is already good: %o', async (flags, text) => {
    api.createFareWatch.mockResolvedValue({ ...WATCH, baseline_price: 480, already_watching: false, already_below_target: false, already_low: false, ...flags })
    await render(<WatchFareButton trip={TRIP} />)
    await act(async () => button('Watch fare').click())
    await act(async () => button('Start watching').click())
    expect(document.querySelector('[role="dialog"]').textContent).toContain(text)
  })

  it('pre-ticks nearby dates from the fare calendar and hides email without SMTP', async () => {
    alerts.caps = { ...alerts.caps, email: false }
    await render(<WatchFareButton trip={TRIP} defaultFlexible label="Watch these dates" />)
    await act(async () => button('Watch these dates').click())
    const dialog = document.querySelector('[role="dialog"]')
    expect(dialog.querySelector('input[type="checkbox"]').checked).toBe(true)
    expect(dialog.textContent).not.toContain('Also email me')
  })

  it('says so when the trip is already watched and never asks about browser alerts', async () => {
    api.createFareWatch.mockResolvedValue({ ...WATCH, already_watching: true })
    await render(<WatchFareButton trip={TRIP} />)
    await act(async () => button('Watch fare').click())
    await act(async () => button('Start watching').click())
    expect(document.body.textContent).toContain('You’re already watching this fare')
    expect(document.body.textContent).not.toContain('heads-up')
  })

  it('shows the server’s reason when creating fails', async () => {
    api.createFareWatch.mockRejectedValue({ response: { status: 409, data: { detail: 'You’re already watching 10 fares — pause or remove one to watch another.' } } })
    await render(<WatchFareButton trip={TRIP} />)
    await act(async () => button('Watch fare').click())
    await act(async () => button('Start watching').click())
    expect(document.querySelector('[role="alert"]').textContent).toContain('10 fares')
  })

  it('does not scold an empty target until the traveller acts', async () => {
    await render(<WatchFareButton trip={TRIP} />)
    await act(async () => button('Watch fare').click())
    const dialog = document.querySelector('[role="dialog"]')
    await act(async () => dialog.querySelector('input[value="below_target"]').click())
    expect(dialog.textContent).not.toContain('Enter a price')
    await act(async () => button('Start watching', dialog).click())
    expect(api.createFareWatch).not.toHaveBeenCalled()
    expect(dialog.textContent).toContain('Enter a price')
  })

  it('keeps keyboard focus inside the dialog', async () => {
    await render(<WatchFareButton trip={TRIP} />)
    await act(async () => button('Watch fare').click())
    const dialog = document.querySelector('[role="dialog"]')
    const focusables = [...dialog.querySelectorAll('button:not([disabled]), input:not([disabled]), a[href]')]
    const first = focusables[0]
    const last = focusables[focusables.length - 1]
    expect(dialog.contains(document.activeElement)).toBe(true)
    last.focus()
    act(() => { document.activeElement.dispatchEvent(new KeyboardEvent('keydown', { key: 'Tab', bubbles: true })) })
    expect(document.activeElement).toBe(first)
    first.focus()
    act(() => { document.activeElement.dispatchEvent(new KeyboardEvent('keydown', { key: 'Tab', shiftKey: true, bubbles: true })) })
    expect(document.activeElement).toBe(last)
  })

  it('closes on Escape', async () => {
    await render(<WatchFareButton trip={TRIP} />)
    await act(async () => button('Watch fare').click())
    // from inside the dialog, as a real key press would be
    const inside = document.querySelector('[role="dialog"] input')
    await act(async () => inside.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true })))
    expect(document.querySelector('[role="dialog"]')).toBeNull()
  })
})

// ── Bell + toast ──────────────────────────────────────────────────────────────

describe('NotificationBell', () => {
  it('labels the unread count and caps the badge at 9+', async () => {
    alerts.unread = 12
    await render(<NotificationBell />)
    const bell = container.querySelector('button[aria-expanded]')
    expect(bell.getAttribute('aria-label')).toBe('Notifications, 12 unread')
    expect(bell.textContent).toBe('9+')
  })

  it('lists the latest alerts; opening one marks it read and goes to its watch', async () => {
    alerts.unread = 1
    api.listNotifications.mockResolvedValue({ items: [
      { id: 3, kind: 'fare_drop', title: 'Berlin → Lisbon dropped to $454 (−$46)', body: 'For 1–8 Dec', data: { watch_id: 7, links: { alerts: '/alerts?watch=7' } }, created_at: new Date().toISOString(), read_at: null },
      { id: 2, kind: 'watch_error', title: 'We couldn’t check Berlin → Lisbon', body: 'x', data: { watch_id: 7 }, created_at: new Date().toISOString(), read_at: '2026-01-01' },
    ] })
    await render(<NotificationBell />)
    await act(async () => container.querySelector('button[aria-expanded]').click())
    expect(api.listNotifications).toHaveBeenCalledWith('tok', { limit: 10 })
    expect(container.textContent).toContain('dropped to $454')
    expect(container.textContent).toContain('Retry')
    await act(async () => button('dropped to $454', container).click())
    expect(alerts.markRead).toHaveBeenCalledWith([3])
    expect(location.search).toBe('?watch=7')
    expect(container.querySelector('[role="region"]')).toBeNull()
  })

  it('has a friendly empty state and Mark all as read', async () => {
    alerts.unread = 0
    api.listNotifications.mockResolvedValue({ items: [] })
    await render(<NotificationBell />)
    await act(async () => container.querySelector('button[aria-expanded]').click())
    expect(container.textContent).toContain('No alerts yet')
    expect(button('Mark all as read', container).disabled).toBe(true)
  })
})

describe('AlertToast', () => {
  it('shows one dismissible toast in a polite live region', async () => {
    alerts.toast = { id: 5, kind: 'fare_target', title: 'Under your target', body: 'b', data: { watch_id: 7 } }
    await render(<AlertToast />)
    const region = container.querySelector('[aria-live="polite"]')
    expect(region.textContent).toContain('Under your target')
    await act(async () => container.querySelector('button[aria-label="Dismiss alert"]').click())
    expect(alerts.dismissToast).toHaveBeenCalled()
  })

  it('opens the watch and marks the alert read', async () => {
    alerts.toast = { id: 5, kind: 'fare_drop', title: 'Dropped', body: 'b', data: { watch_id: 7 } }
    await render(<AlertToast />)
    await act(async () => button('See fare', container).click())
    expect(alerts.markRead).toHaveBeenCalledWith([5])
    expect(location.search).toBe('?watch=7')
  })

  it('leaves on its own after a while', async () => {
    vi.useFakeTimers()
    alerts.toast = { id: 5, kind: 'fare_drop', title: 'Dropped', body: 'b', data: {} }
    await render(<AlertToast />)
    await act(async () => { vi.advanceTimersByTime(10000) })
    expect(alerts.dismissToast).toHaveBeenCalled()
    vi.useRealTimers()
  })
})

// ── Card + page ───────────────────────────────────────────────────────────────

describe('Sparkline', () => {
  it('draws the line, the target and a text summary', async () => {
    await render(<Sparkline history={[{ price: 500 }, { price: 454 }]} target={450} />)
    const svg = container.querySelector('svg')
    expect(svg.getAttribute('aria-label')).toBe('Price over 2 checks: from $500 to $454, low $454. Your target is $450.')
    expect(container.querySelector('[data-testid="spark-target"]')).not.toBeNull()
  })

  it('explains a single point', async () => {
    await render(<Sparkline history={[{ price: 500 }]} />)
    expect(container.textContent).toContain('after the next check')
  })
})

describe('WatchCard', () => {
  const props = (over = {}) => ({
    watch: WATCH, onCheck: vi.fn(), onUpdate: vi.fn(async () => true), onDelete: vi.fn(),
    onReplan: vi.fn(), onBook: vi.fn(), ...over,
  })

  it('shows price, change since watching, lowest seen and Google’s verdict', async () => {
    await render(<WatchCard {...props()} />)
    const text = container.textContent
    expect(text).toContain('Berlin → Lisbon')
    expect(text).toContain('Price dropped')
    expect(text).toContain('$454')
    expect(text).toContain('$46 less than when you started')
    expect(text).toContain('Lowest seen $454')
    expect(text).toContain('Google: low for this route')
    expect(text).toContain('total for 2 travellers')
  })

  it('confirms delete inline, then deletes', async () => {
    const p = props()
    await render(<WatchCard {...p} />)
    await act(async () => button('Delete', container).click())
    expect(container.textContent).toContain('Stop watching?')
    expect(document.querySelector('[role="dialog"]')).toBeNull()
    await act(async () => button('Keep', container).click())
    expect(container.textContent).not.toContain('Stop watching?')
    await act(async () => button('Delete', container).click())
    const confirm = [...container.querySelectorAll('[role="group"] button')].find(b => b.textContent === 'Delete')
    await act(async () => confirm.click())
    expect(p.onDelete).toHaveBeenCalled()
  })

  it('offers Retry for a watch with a problem, and Resume for a paused one', async () => {
    const p = props({ watch: { ...WATCH, status: 'error' } })
    await render(<WatchCard {...p} />)
    await act(async () => button('Retry', container).click())
    expect(p.onUpdate).toHaveBeenCalledWith({ status: 'active' })
    expect(button('Check now', container)).toBeUndefined()
    const q = props({ watch: { ...WATCH, status: 'paused' } })
    await render(<WatchCard {...q} />)
    await act(async () => button('Resume', container).click())
    expect(q.onUpdate).toHaveBeenCalledWith({ status: 'active' })
  })

  it('suggests the cheaper nearby departure for flexible watches', async () => {
    const watch = { ...WATCH, flexible_days: 3, history: [{ price: 500, cheapest_price: 430, cheapest_departure_date: '2099-12-03', cheapest_return_date: '2099-12-10' }] }
    const p = props({ watch })
    await render(<WatchCard {...p} />)
    const nearby = button('save $70', container)
    expect(nearby).toBeDefined()
    await act(async () => nearby.click())
    expect(p.onReplan).toHaveBeenCalledWith(true)
  })

  it('edits the alert mode with a target', async () => {
    const p = props()
    await render(<WatchCard {...p} />)
    await act(async () => button('Edit', container).click())
    const form = container.querySelector('form[aria-label="Edit alert settings"]')
    act(() => setValue(form.querySelector('input[aria-label="Target price in US dollars"]'), '420'))
    await act(async () => button('Save', form).click())
    expect(p.onUpdate).toHaveBeenCalledWith({ alert_mode: 'below_target', target_price: 420, flexible_days: 0, email_enabled: false })
  })

  it('shows the friendly problem and no contradictory “getting price” text', async () => {
    const watch = { ...WATCH, status: 'error', baseline_price: null, last_price: null, problem: 'Live fares took too long to answer.' }
    await render(<WatchCard {...props({ watch })} />)
    expect(container.textContent).toContain('Live fares took too long to answer.')
    expect(container.textContent).toContain('No price yet')
    expect(container.textContent).not.toContain('Getting today’s price')
  })

  it('past trips keep only Delete', async () => {
    await render(<WatchCard {...props({ watch: { ...WATCH, status: 'expired' } })} />)
    expect(container.textContent).toContain('Ended')
    expect(button('Re-plan', container)).toBeUndefined()
    expect(button('Check now', container)).toBeUndefined()
    expect(button('Delete', container)).toBeDefined()
  })
})

describe('AlertsPage', () => {
  it('has a helpful empty state', async () => {
    api.listFareWatches.mockResolvedValue([])
    await render(<AlertsPage />, '/alerts')
    expect(container.textContent).toContain('No fares watched yet')
    await act(async () => button('Search flights', container).click())
    expect(location.pathname).toBe('/')
  })

  it('groups active and past watches', async () => {
    api.listFareWatches.mockResolvedValue([WATCH, { ...WATCH, id: 8, status: 'expired' }])
    await render(<AlertsPage />, '/alerts')
    expect(container.querySelector('#alerts-active').textContent).toContain('(1)')
    expect(container.querySelector('#alerts-past').textContent).toContain('(1)')
  })

  it('Check now shows the outcome, including the daily-limit message', async () => {
    api.listFareWatches.mockResolvedValue([WATCH])
    api.checkFareWatchNow.mockResolvedValueOnce({ ...WATCH, last_price: 430, check_status: 'checked', notification: { title: 'Berlin → Lisbon dropped to $430 (−$24)' } })
    await render(<AlertsPage />, '/alerts')
    await act(async () => button('Check now', container).click())
    expect(container.textContent).toContain('dropped to $430')
    expect(alerts.watchesChanged).toHaveBeenCalled()
    api.checkFareWatchNow.mockRejectedValueOnce({ response: { status: 429, data: { detail: 'We’ve used today’s live fare checks — we’ll check again tomorrow.' } } })
    await act(async () => button('Check now', container).click())
    expect(container.textContent).toContain('check again tomorrow')
  })

  it.each([
    [{ check_status: 'errored' }, 'checks are on hold'],
    [{ check_status: 'failed' }, 'try again within the hour'],
    [{ check_status: 'expired', status: 'expired' }, 'has departed'],
    [{ check_status: 'postponed' }, 'tomorrow'],
    [{ check_status: 'checked', last_price: 454, notification: null }, 'Checked just now: $454'],
    [{ check_status: 'checked', last_price: null, baseline_price: null, notification: null }, 'no fares were found'],
    [{ check_status: 'skipped' }, 'isn’t being watched'],
  ])('Check now result %o reads “%s”', async (res, text) => {
    api.listFareWatches.mockResolvedValue([WATCH])
    api.checkFareWatchNow.mockResolvedValueOnce({ ...WATCH, notification: null, ...res })
    await render(<AlertsPage />, '/alerts')
    await act(async () => button('Check now', container).click())
    expect(container.textContent).toContain(text)
  })

  it('a Check-now alert is not shown again as a toast', async () => {
    api.listFareWatches.mockResolvedValue([WATCH])
    api.checkFareWatchNow.mockResolvedValueOnce({ ...WATCH, check_status: 'checked', notification: { id: 41, title: 'Dropped' } })
    await render(<AlertsPage />, '/alerts')
    await act(async () => button('Check now', container).click())
    expect(alerts.markSeen).toHaveBeenCalledWith(41)
    expect(alerts.markSeen.mock.invocationCallOrder[0]).toBeLessThan(alerts.refresh.mock.invocationCallOrder[0])
  })

  it('Re-plan runs the trip as a search with the traveller’s preferences', async () => {
    api.listFareWatches.mockResolvedValue([WATCH])
    await render(<AlertsPage />, '/alerts')
    await act(async () => button('Re-plan with this fare', container).click())
    expect(pending).toHaveBeenCalledWith(expect.objectContaining({
      origin: 'Berlin, Germany', destination: 'Lisbon, Portugal', departure_date: '2099-12-01',
      nationality: 'German', interests: ['food'], num_travelers: 2,
    }))
    expect(location.pathname).toBe('/')
  })

  it('an email “Re-plan” link re-plans right away', async () => {
    api.listFareWatches.mockResolvedValue([WATCH])
    await render(<AlertsPage />, '/alerts?watch=7&replan=1')
    expect(pending).toHaveBeenCalledTimes(1)
    expect(location.pathname).toBe('/')
  })

  it('shows a retryable error when loading fails', async () => {
    api.listFareWatches.mockRejectedValueOnce(new Error('offline')).mockResolvedValueOnce([])
    await render(<AlertsPage />, '/alerts')
    expect(container.querySelector('[role="alert"]').textContent).toContain('Couldn’t load')
    await act(async () => button('Try again', container).click())
    expect(container.textContent).toContain('No fares watched yet')
  })
})
