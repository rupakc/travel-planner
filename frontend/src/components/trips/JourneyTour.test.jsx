// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { act } from 'react'
import { createRoot } from 'react-dom/client'

vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (k) => k }) }))
const journey = { enabled: true }
vi.mock('../../services/accountApi', () => ({ putOnboarding: vi.fn() }))
vi.mock('../../hooks/useJourney', () => ({ useJourney: () => journey }))
import JourneyTour from './JourneyTour'
import { putOnboarding } from '../../services/accountApi'

globalThis.IS_REACT_ACT_ENVIRONMENT = true
const box = { left: 10, top: 10, width: 80, height: 30, right: 90, bottom: 40 }

function addAnchor(name) {
  const el = document.createElement('button')
  el.setAttribute('data-tour', name)
  el.getBoundingClientRect = () => box
  document.body.appendChild(el)
}

describe('JourneyTour', () => {
  let container, root
  const render = (props) => act(() => root.render(<JourneyTour username="ana" visible {...props} />))
  const titles = () => [...document.querySelectorAll('[role="dialog"] h2')].map((h) => h.textContent)
  const dialog = () => document.querySelector('[role="dialog"]')
  const click = (tid) => act(() => document.querySelector(`[data-tid="${tid}"]`).click())

  beforeEach(() => {
    vi.useFakeTimers()
    localStorage.clear()
    journey.enabled = true
    ;['nav-trips', 'nav-explore', 'nav-alerts', 'nav-play', 'nav-you'].forEach(addAnchor)
    container = document.createElement('div')
    document.body.appendChild(container)
    root = createRoot(container)
  })
  afterEach(() => {
    act(() => root.unmount())
    document.body.innerHTML = ''
    vi.useRealTimers()
  })

  it('does not open before onboarding is done', () => {
    render({ onboardingDone: false })
    act(() => vi.advanceTimersByTime(5000))
    expect(dialog()).toBeNull()
  })

  it('opens once after onboarding, and not again once finished', () => {
    render({ onboardingDone: true })
    act(() => vi.advanceTimersByTime(5000))
    expect(titles()).toEqual(['steps.trips.title'])
    for (let i = 0; i < 4; i++) click('tour.next')
    click('tour.start')
    expect(dialog()).toBeNull()
    act(() => root.unmount())
    root = createRoot(container)
    render({ onboardingDone: true })
    act(() => vi.advanceTimersByTime(5000))
    expect(dialog()).toBeNull()
  })

  it('skips a step whose anchor is missing', () => {
    document.querySelector('[data-tour="nav-alerts"]').remove()
    render({ onboardingDone: true })
    act(() => vi.advanceTimersByTime(5000))
    const seen = [titles()[0]]
    for (let i = 0; i < 3; i++) { click('tour.next'); seen.push(titles()[0]) }
    expect(seen).toEqual(['steps.trips.title', 'steps.explore.title', 'steps.play.title', 'steps.you.title'])
  })

  it('replays on the replay event even when already seen', () => {
    localStorage.setItem('tp_tour_done:journey:ana', '1')
    render({ onboardingDone: true })
    act(() => vi.advanceTimersByTime(5000))
    expect(dialog()).toBeNull()
    act(() => { window.dispatchEvent(new Event('voyager:replay-journey-tour')) })
    expect(titles()).toEqual(['steps.trips.title'])
  })

  it('renders nothing when the journey is off', () => {
    journey.enabled = false
    render({ onboardingDone: true })
    act(() => vi.advanceTimersByTime(5000))
    act(() => { window.dispatchEvent(new Event('voyager:replay-journey-tour')) })
    expect(dialog()).toBeNull()
  })

  it('skips a zero-size duplicate anchor and spotlights the visible one', () => {
    const hidden = document.querySelector('[data-tour="nav-trips"]')
    hidden.getBoundingClientRect = () => ({ left: 0, top: 0, width: 0, height: 0, right: 0, bottom: 0 })
    addAnchor('nav-trips') // the visible twin
    render({ onboardingDone: true })
    act(() => vi.advanceTimersByTime(5000))
    expect(titles()).toEqual(['steps.trips.title'])
  })

  it('never reports onboarding when finished', () => {
    render({ onboardingDone: true })
    act(() => vi.advanceTimersByTime(5000))
    for (let i = 0; i < 4; i++) click('tour.next')
    click('tour.start')
    expect(putOnboarding).not.toHaveBeenCalled()
  })
})
