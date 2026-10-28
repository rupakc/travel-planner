// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import useFirstRunTour from './useFirstRunTour'
import { markTourDone, isTourDone } from '../utils/tour'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

describe('useFirstRunTour', () => {
  let container, root, tour

  function Harness(props) {
    tour = useFirstRunTour({ delayMs: 600, ...props })
    return null
  }
  const render = (props) => act(() => root.render(<Harness username="ana" visible eligible {...props} />))
  const wait = (ms) => act(() => { vi.advanceTimersByTime(ms) })

  beforeEach(() => {
    vi.useFakeTimers()
    localStorage.clear()
    container = document.createElement('div')
    root = createRoot(container)
  })

  afterEach(() => {
    act(() => root.unmount())
    vi.useRealTimers()
  })

  it('opens for a first-time user once the page has settled', () => {
    render()
    expect(tour.open).toBe(false)
    wait(600)
    expect(tour.open).toBe(true)
  })

  it('stays closed once this user has finished it', () => {
    markTourDone('ana')
    render()
    wait(600)
    expect(tour.open).toBe(false)
  })

  it('does not open for users it is not meant for (e.g. who already have search history)', () => {
    render({ eligible: false })
    wait(600)
    expect(tour.open).toBe(false)
  })

  it('only shows while the search form is on screen', () => {
    render({ visible: false })
    wait(600)
    expect(tour.open).toBe(false)
    render({ visible: true })
    wait(600)
    expect(tour.open).toBe(true)
    // Navigating away mid-tour hides it without marking it done
    render({ visible: false })
    expect(tour.open).toBe(false)
    expect(isTourDone('ana')).toBe(false)
  })

  it('closing marks it done for this user only', () => {
    render()
    wait(600)
    act(() => tour.close())
    expect(tour.open).toBe(false)
    expect(isTourDone('ana')).toBe(true)
    expect(isTourDone('ben')).toBe(false)
  })

  it('can be replayed on request even after it was finished', () => {
    markTourDone('ana')
    render({ eligible: false })
    act(() => tour.start())
    expect(tour.open).toBe(true)
  })

  it('waits for a user', () => {
    render({ username: undefined })
    wait(600)
    expect(tour.open).toBe(false)
  })
})
