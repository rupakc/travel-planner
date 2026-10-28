// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { act, useState } from 'react'
import { createRoot } from 'react-dom/client'
import OnboardingTour from './OnboardingTour'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

const steps = [
  { id: 'form', target: '[data-tour="form"]', title: 'Plan a trip', body: 'Fill the form.' },
  { id: 'missing', target: '[data-tour="nowhere"]', title: 'Missing', body: 'Never shown.' },
  { id: 'hidden', target: '[data-tour="hidden"]', title: 'Hidden', body: 'Zero size, never shown.' },
  { id: 'plan', target: '[data-tour="plan"]', title: 'Search', body: 'Press the button.' },
  { id: 'wrap', target: null, title: 'Build your plan', body: 'Centred final step.' },
]

// jsdom lays nothing out, so give the "visible" targets a real box
const addTarget = (name, box) => {
  const el = document.createElement('div')
  el.setAttribute('data-tour', name)
  el.getBoundingClientRect = () => box
  document.body.appendChild(el)
  return el
}
const box = { left: 100, top: 100, width: 300, height: 60, right: 400, bottom: 160 }
const zeroBox = { left: 0, top: 0, width: 0, height: 0, right: 0, bottom: 0 }

describe('OnboardingTour', () => {
  let container, root, onClose

  const render = (props = {}) => act(() => root.render(
    <OnboardingTour open steps={steps} onClose={onClose} {...props} />,
  ))
  const dialog = () => document.querySelector('[role="dialog"]')
  const button = (label) => [...document.querySelectorAll('[role="dialog"] button')].find((b) => b.textContent.trim() === label)
  const key = (k, opts = {}) => act(() => {
    document.activeElement.dispatchEvent(new KeyboardEvent('keydown', { key: k, bubbles: true, ...opts }))
  })

  beforeEach(() => {
    onClose = vi.fn()
    addTarget('form', box)
    addTarget('hidden', zeroBox)
    addTarget('plan', box)
    container = document.createElement('div')
    document.body.appendChild(container)
    root = createRoot(container)
  })

  afterEach(() => {
    act(() => root.unmount())
    document.body.innerHTML = ''
  })

  it('renders nothing when closed', () => {
    render({ open: false })
    expect(dialog()).toBeNull()
  })

  it('opens on the first step as an accessible dialog, focused on Next', () => {
    render()
    expect(dialog().getAttribute('aria-modal')).toBe('true')
    const title = document.getElementById(dialog().getAttribute('aria-labelledby'))
    expect(title.textContent).toBe('Plan a trip')
    expect(dialog().textContent).toContain('1 of 3')
    expect(document.activeElement).toBe(button('Next'))
  })

  it('moves focus to the card without scrolling, which would cancel scrolling to the step', () => {
    const focus = vi.spyOn(HTMLElement.prototype, 'focus')
    render()
    act(() => button('Next').click())
    const calls = focus.mock.calls
    expect(calls.length).toBeGreaterThan(0)
    calls.forEach((args) => expect(args[0]).toEqual({ preventScroll: true }))
    focus.mockRestore()
  })

  it('skips steps whose element is missing or not visible', () => {
    render()
    act(() => button('Next').click())
    expect(dialog().textContent).toContain('Search')
    expect(dialog().textContent).toContain('2 of 3')
  })

  it('goes back with Back', () => {
    render()
    act(() => button('Next').click())
    act(() => button('Back').click())
    expect(dialog().textContent).toContain('Plan a trip')
    expect(button('Back')).toBeUndefined()
  })

  it('finishes from the last step', () => {
    render()
    act(() => button('Next').click())
    act(() => button('Next').click())
    expect(dialog().textContent).toContain('Build your plan')
    act(() => button('Get started').click())
    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it('can be skipped', () => {
    render()
    act(() => button('Skip tour').click())
    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it('closes with Escape, even after focus has left the card', () => {
    // A parent that really closes the tour, so Escape can't pass by accident
    function Parent() {
      const [open, setOpen] = useState(true)
      return <OnboardingTour open={open} steps={steps} onClose={() => setOpen(false)} />
    }
    act(() => root.render(<Parent />))
    act(() => document.activeElement.blur())
    act(() => { document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true })) })
    expect(dialog()).toBeNull()
  })

  it('announces each step: focus moves into a fresh dialog with the new title', () => {
    render()
    const first = dialog()
    act(() => button('Next').click())
    expect(dialog()).not.toBe(first)
    expect(dialog().contains(document.activeElement)).toBe(true)
    expect(document.getElementById(dialog().getAttribute('aria-labelledby')).textContent).toBe('Search')
  })

  it('a click on the dimmed page does not pull focus out of the card', () => {
    render()
    const backdrop = document.querySelector('[data-tour-backdrop]')
    const event = new MouseEvent('mousedown', { bubbles: true, cancelable: true })
    act(() => { backdrop.dispatchEvent(event) })
    expect(event.defaultPrevented).toBe(true)
  })

  it('starts again from the first step when reopened', () => {
    render()
    act(() => button('Next').click())
    render({ open: false })
    render({ open: true })
    expect(dialog().textContent).toContain('Plan a trip')
  })

  it('keeps keyboard focus inside the card', () => {
    render()
    const focusable = [...dialog().querySelectorAll('button')]
    focusable[focusable.length - 1].focus()
    key('Tab')
    expect(document.activeElement).toBe(focusable[0])
    key('Tab', { shiftKey: true })
    expect(document.activeElement).toBe(focusable[focusable.length - 1])
  })

  it('Tab from outside the card brings focus back into it', () => {
    render()
    act(() => document.activeElement.blur())
    act(() => { document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Tab', bubbles: true, cancelable: true })) })
    expect(dialog().contains(document.activeElement)).toBe(true)
  })

  it('returns focus to where it was when the tour closes', () => {
    const before = document.createElement('button')
    document.body.appendChild(before)
    before.focus()
    render()
    expect(document.activeElement).not.toBe(before)
    render({ open: false })
    expect(document.activeElement).toBe(before)
  })

  it('shows a centred card when no step has a visible target', () => {
    render({ steps: [steps[1], steps[4]] })
    expect(dialog().textContent).toContain('Build your plan')
    expect(dialog().textContent).not.toContain('of')
    expect(button('Get started')).toBeDefined()
  })
})
