// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { MemoryRouter } from 'react-router-dom'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

const mocks = vi.hoisted(() => ({
  journey: { enabled: true },
  online: true,
  checkIn: vi.fn(),
  putPlace: vi.fn(),
  enqueue: vi.fn(),
}))

vi.mock('../../hooks/useJourney', () => ({ useJourney: () => mocks.journey }))
vi.mock('../../context/AuthContext', () => ({ useAuth: () => ({ user: { id: 7 } }) }))
vi.mock('../../offline/useOnline', () => ({ useOnline: () => mocks.online }))
vi.mock('../../offline/outbox', () => ({ enqueue: (...a) => mocks.enqueue(...a) }))
vi.mock('../../game/announce', () => ({ announceGame: vi.fn() }))
vi.mock('../../telemetry/client', () => ({ emit: vi.fn() }))
vi.mock('../../services/tripsApi', () => ({
  checkIn: (...a) => mocks.checkIn(...a),
  putPlace: (...a) => mocks.putPlace(...a),
  listCheckins: vi.fn().mockResolvedValue({ days: [], streak: null }),
  listPlaces: vi.fn().mockResolvedValue({ places: [] }),
}))

import TodayView from './TodayView'
import { localToday } from '../../utils/tripPhase'

const itinerary = { days: [{ day_number: 1, city: 'Lisbon', slots: [
  { time_of_day: 'morning', activity: 'Tram 28' },
  { time_of_day: 'afternoon', activity: 'Belém Tower', lat: 38.69, lng: -9.21 },
] }] }
const trip = { id: 12, destination: 'Lisbon', start_date: localToday(), end_date: localToday() }
let container, root
const withSel = (selections) => ({ ...trip, selections })
const view = async (props = {}) => {
  await act(async () => root.render(<MemoryRouter><TodayView trip={props.trip || withSel(props.selections)} token="tok" /></MemoryRouter>))
}
const tid = (id) => container.querySelector(`[data-tid="${id}"]`)
const text = () => container.textContent
const click = async (el) => { await act(async () => { el.dispatchEvent(new MouseEvent('click', { bubbles: true })) }) }
const clickText = (label) => click([...container.querySelectorAll('button')].find((b) => b.textContent.includes(label)))

const reduced = (matches) => { window.matchMedia = vi.fn().mockReturnValue({ matches, addEventListener() {}, removeEventListener() {} }) }

beforeEach(() => {
  mocks.journey = { enabled: true }; mocks.online = true
  mocks.checkIn.mockReset(); mocks.putPlace.mockReset(); mocks.enqueue.mockReset()
  reduced(false)
  container = document.createElement('div'); document.body.appendChild(container); root = createRoot(container)
})
afterEach(() => { act(() => root.unmount()); container.remove(); vi.restoreAllMocks() })

describe('TodayView', () => {
  it('recomputes next up every minute', async () => {
    vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval', 'Date'] })
    try {
      vi.setSystemTime(new Date(2027, 3, 1, 8, 0))
      const t1 = { ...trip, start_date: '2027-04-01', end_date: '2027-04-01' }
      await view({ trip: { ...t1, selections: { itinerary } } })
      const next = () => tid('today-next-up').textContent
      expect(next()).toContain('Tram 28')
      vi.setSystemTime(new Date(2027, 3, 1, 13, 5))
      await act(async () => { vi.advanceTimersByTime(60000) })
      expect(next()).toContain('Belém Tower')
    } finally { vi.useRealTimers() }
  })

  it('ignores a second tap on "I went here" while the first is in flight', async () => {
    let release
    mocks.putPlace.mockReturnValue(new Promise((r) => { release = r }))
    await view({ selections: { itinerary } })
    await click(tid('today-visited-0'))
    await click(tid('today-visited-0'))
    expect(mocks.putPlace).toHaveBeenCalledTimes(1)
    await act(async () => release({ game: null }))
  })

  it('shows the day header and check-in streak, and the stamp on a new country', async () => {
    mocks.checkIn.mockResolvedValue({ day_index: 1, city: 'Lisbon', country_code: 'PT', new_country: true, streak: { current: 3 }, game: null })
    await view({ selections: { itinerary } })
    expect(text()).toContain('Day 1 in Lisbon')
    await clickText('Check in for today')
    expect(text()).toContain('3-day streak')
    expect(tid('today-stamp')).not.toBeNull()
  })

  it('plays no stamp under reduced motion', async () => {
    reduced(true)
    mocks.checkIn.mockResolvedValue({ new_country: true, country_code: 'PT', streak: { current: 1 } })
    await view({ selections: { itinerary } })
    await clickText('Check in for today')
    expect(text()).toContain('1-day streak')
    expect(tid('today-stamp')).toBeNull()
    expect(tid('today-new-country')).not.toBeNull()
  })

  it('renders without itinerary', async () => {
    await view({ selections: {} })
    expect(text()).toContain('Day 1 in Lisbon')
    expect(text()).toContain('No plan for today yet.')
    expect(text()).toContain('Near me')
  })

  it('lists slots with derived times and directions', async () => {
    await view({ selections: { itinerary } })
    expect(text()).toContain('Belém Tower')
    expect(tid('today-directions-1').getAttribute('href')).toContain('destination=38.69,-9.21')
    expect(text()).toContain('09:00–12:00')
  })

  it('offline "I went here" enqueues the request using the pack', async () => {
    mocks.online = false
    await view({ selections: { itinerary } })
    await click(tid('today-visited-0'))
    expect(mocks.enqueue).toHaveBeenCalledTimes(1)
    const [userId, item] = mocks.enqueue.mock.calls[0]
    expect(userId).toBe(7)
    expect(item).toMatchObject({ method: 'PUT', path: '/trips/12/places/activity:tram-28' })
    expect(item.body).toMatchObject({ name: 'Tram 28', visited: true })
    expect(mocks.putPlace).not.toHaveBeenCalled()
  })

  it('before the trip shows the start-date message', async () => {
    await view({ trip: { ...trip, start_date: '2099-01-10', end_date: '2099-01-12' } })
    expect(text()).toContain('Today starts on')
    expect(tid('today-checkin')).toBeNull()
  })

  it('after the trip ends shows the start-date message', async () => {
    await view({ trip: { ...trip, start_date: '2001-01-10', end_date: '2001-01-12' } })
    expect(text()).toContain('Today starts on')
  })

  it('renders nothing when the journey is off', async () => {
    mocks.journey = { enabled: false }
    await view()
    expect(container.innerHTML).toBe('')
  })
})
