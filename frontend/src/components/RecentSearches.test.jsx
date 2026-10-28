// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import RecentSearches, { OPEN_STORAGE_KEY } from './RecentSearches'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

const entries = [
  { id: 'a', search: { origin: 'New York', destination: 'Tokyo', departure_date: '2027-04-01', return_date: '2027-04-08', interests: ['food'] } },
  { id: 'b', search: { origin: 'London', destination: 'Lisbon', departure_date: '2027-05-01', interests: [] } },
]

describe('RecentSearches accordion', () => {
  let container, root

  const render = (props = {}) => act(() => root.render(
    <RecentSearches entries={entries} today="2027-01-01" onLoad={() => {}} onRerun={() => {}} onRemove={() => {}} {...props} />,
  ))
  const remount = (props) => {
    act(() => root.unmount())
    root = createRoot(container)
    render(props)
  }
  const toggle = () => container.querySelector('button[aria-controls]')
  const cards = () => container.querySelectorAll('button[title^="Load into the form"]')

  beforeEach(() => {
    localStorage.clear()
    container = document.createElement('div')
    document.body.appendChild(container)
    root = createRoot(container)
  })

  afterEach(() => {
    act(() => root.unmount())
    container.remove()
    vi.restoreAllMocks()
  })

  it('starts open the first time, showing every card', () => {
    render()
    expect(toggle().getAttribute('aria-expanded')).toBe('true')
    expect(cards()).toHaveLength(2)
  })

  it('the header shows how many searches there are', () => {
    render()
    expect(toggle().textContent).toContain('2')
  })

  it('collapses and expands from the header', () => {
    render()
    act(() => toggle().click())
    expect(toggle().getAttribute('aria-expanded')).toBe('false')
    expect(cards()).toHaveLength(0)
    act(() => toggle().click())
    expect(toggle().getAttribute('aria-expanded')).toBe('true')
    expect(cards()).toHaveLength(2)
  })

  it('remembers a collapsed section the next time it is shown', () => {
    render()
    act(() => toggle().click())
    expect(localStorage.getItem(OPEN_STORAGE_KEY)).toBe('false')
    remount()
    expect(toggle().getAttribute('aria-expanded')).toBe('false')
    expect(cards()).toHaveLength(0)
  })

  it('still works when browser storage is unavailable', () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => { throw new Error('blocked') })
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('blocked') })
    render()
    expect(cards()).toHaveLength(2)
    act(() => toggle().click())
    expect(cards()).toHaveLength(0)
  })

  it('renders nothing when there are no recent searches', () => {
    render({ entries: [] })
    expect(container.innerHTML).toBe('')
  })
})
