// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { StressTestSection } from './ResultsPage'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

const ORIGINAL = { overall: 'amber', summary: 'Original audit', score: 60, findings: [{ severity: 'high', category: 'pacing', issue: 'Original finding' }] }
const RECHECKED = { overall: 'green', summary: 'Edited audit', score: 90, findings: [{ severity: 'low', category: 'timing', issue: 'Edited finding' }] }

describe('StressTestSection re-check', () => {
  let container, root
  beforeEach(() => {
    container = document.createElement('div')
    document.body.appendChild(container)
    root = createRoot(container)
  })
  afterEach(() => {
    act(() => root.unmount())
    container.remove()
  })

  const render = (props) => act(() => root.render(<StressTestSection data={ORIGINAL} onRecheck={() => {}} {...props} />))
  const recheckButton = () => [...container.querySelectorAll('button')].find((b) => /Re-check/.test(b.textContent))
  const text = () => container.textContent

  it('offers no re-check while the layout is unchanged', () => {
    render({ layoutMoved: false })
    expect(recheckButton()).toBeUndefined()
    expect(text()).not.toContain('Checked against the original itinerary')
  })

  it('shows the button next to the original-itinerary note once moved, and runs on click', () => {
    const onRecheck = vi.fn()
    render({ layoutMoved: true, onRecheck })
    expect(text()).toContain("Checked against the original itinerary — your moves aren't re-checked.")
    expect(recheckButton().textContent).toBe('Re-check my edited plan')
    expect(recheckButton().disabled).toBe(false)
    act(() => recheckButton().click())
    expect(onRecheck).toHaveBeenCalledTimes(1)
  })

  it('disables the button with a spinner while running', () => {
    render({ layoutMoved: true, rechecking: true })
    expect(recheckButton().textContent).toBe('Re-checking…')
    expect(recheckButton().disabled).toBe(true)
    expect(recheckButton().querySelector('.animate-spin')).not.toBeNull()
    expect(text()).toContain('Original finding')
  })

  it('replaces the findings in place with a fresh re-check and hides the button', () => {
    render({ layoutMoved: true, recheck: { data: RECHECKED, stale: false } })
    expect(text()).toContain('Edited finding')
    expect(text()).toContain('Edited audit')
    expect(text()).not.toContain('Original finding')
    expect(text()).toContain('Checked against your edited itinerary')
    expect(text()).not.toContain('Checked against the original itinerary')
    expect(recheckButton()).toBeUndefined()
  })

  it('flags a stale re-check and offers the button again', () => {
    render({ layoutMoved: true, recheck: { data: RECHECKED, stale: true } })
    expect(text()).toContain('Edited finding')
    expect(text()).toContain('Your plan changed since this check — re-check again')
    expect(recheckButton().textContent).toBe('Re-check my edited plan')
  })

  it('shows an error and keeps the previous findings', () => {
    render({ layoutMoved: true, recheckError: 'Too many requests' })
    expect(text()).toContain('Too many requests')
    expect(text()).toContain('Original finding')
    expect(recheckButton()).toBeDefined()
    render({ layoutMoved: true, recheck: { data: RECHECKED, stale: true }, recheckError: "Couldn't re-check — try again" })
    expect(text()).toContain("Couldn't re-check — try again")
    expect(text()).toContain('Edited finding')
  })

  it('shows the original once the layout is back to unchanged', () => {
    render({ layoutMoved: false, recheck: { data: RECHECKED, stale: true } })
    expect(text()).toContain('Original finding')
    expect(text()).not.toContain('Edited finding')
    expect(recheckButton()).toBeUndefined()
  })
})
