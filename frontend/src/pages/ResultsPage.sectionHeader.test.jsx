// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { SectionHeader, sectionBodyId } from './ResultsPage'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

const verification = { level: 'verified', label: 'Verified', summary: 'ok', checks: [], pending: false }

describe('SectionHeader collapse toggle', () => {
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

  const render = (props) => act(() => root.render(
    <SectionHeader agent="hotels" status="done" isOpen onToggle={() => {}} verification={verification}
      actions={<button type="button" onClick={(e) => e.stopPropagation()}>Filters</button>} {...props} />,
  ))
  const toggle = () => container.querySelector('button[aria-expanded]:not([aria-haspopup])')

  it('is a real, focusable button wired to the section body', () => {
    render({ isOpen: true })
    const t = toggle()
    expect(t).not.toBeNull()
    expect(t.tagName).toBe('BUTTON')
    expect(t.getAttribute('type')).toBe('button')
    expect(t.textContent).toContain('Hotels')
    expect(t.getAttribute('aria-expanded')).toBe('true')
    expect(t.getAttribute('aria-controls')).toBe(sectionBodyId('hotels'))
    t.focus()
    expect(document.activeElement).toBe(t)
    render({ isOpen: false })
    expect(toggle().getAttribute('aria-expanded')).toBe('false')
  })

  it('keeps the verification chip and actions outside the toggle button', () => {
    render({})
    const t = toggle()
    expect(t.querySelector('button, a, input')).toBeNull()
    const chip = container.querySelector('button[aria-haspopup="dialog"]')
    expect(chip).not.toBeNull()
    expect(t.contains(chip)).toBe(false)
    const filters = [...container.querySelectorAll('button')].find((b) => b.textContent === 'Filters')
    expect(t.contains(filters)).toBe(false)
  })

  it('toggles exactly once from the button or the header row, never from the chip or actions', () => {
    const onToggle = vi.fn()
    render({ onToggle })
    act(() => toggle().click())
    expect(onToggle).toHaveBeenCalledTimes(1)
    act(() => container.firstChild.click())
    expect(onToggle).toHaveBeenCalledTimes(2)
    act(() => container.querySelector('button[aria-haspopup="dialog"]').click())
    act(() => [...container.querySelectorAll('button')].find((b) => b.textContent === 'Filters').click())
    expect(onToggle).toHaveBeenCalledTimes(2)
  })
})
