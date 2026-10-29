// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach } from 'vitest'
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import VerificationBadge, { VerificationConflictBanner, FoundOnlineBadge } from './VerificationBadge'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

const v = (over = {}) => ({
  level: 'verified',
  label: 'Verified',
  summary: 'Matches our reference table.',
  checks: [
    { label: 'Matches our reference table', status: 'pass', detail: 'Same visa type', url: 'https://example.gov/visa' },
    { label: 'Prices are estimates', status: 'info', detail: 'AI estimates', url: null },
    { label: 'Official source differs', status: 'fail', detail: 'Check it', url: 'javascript:alert(1)' },
  ],
  items_verified: null,
  items_total: null,
  pending: false,
  ...over,
})

describe('VerificationBadge', () => {
  let container, root
  const render = (ui) => act(() => root.render(ui))
  const button = () => container.querySelector('button')
  const popover = () => document.body.querySelector('[role="dialog"]')
  const key = (target, k, init = {}) => act(() => {
    target.dispatchEvent(new KeyboardEvent('keydown', { key: k, bubbles: true, cancelable: true, ...init }))
  })

  beforeEach(() => {
    container = document.createElement('div')
    document.body.appendChild(container)
    root = createRoot(container)
  })
  afterEach(() => {
    act(() => root.unmount())
    container.remove()
  })

  it.each([
    ['verified', 'Verified', 'Verified', 'emerald'],
    ['partial', 'Partly verified', 'Partly verified', 'amber'],
    ['unverified', 'AI-generated', 'AI-generated', 'gray'],
    ['conflict', 'Check details', 'Check details', 'rose'],
  ])('renders the %s chip', (level, label, text, colour) => {
    render(<VerificationBadge verification={v({ level, label })} />)
    expect(button().textContent).toBe(text)
    expect(button().className).toContain(`text-${colour}-`)
  })

  it('shows Checking… while pending, regardless of level', () => {
    render(<VerificationBadge verification={v({ level: 'unverified', label: 'AI-generated', pending: true })} />)
    expect(button().textContent).toBe('Checking…')
    expect(button().querySelector('.animate-spin')).not.toBeNull()
  })

  it('renders nothing without verification', () => {
    render(<VerificationBadge verification={undefined} />)
    expect(container.innerHTML).toBe('')
    render(<VerificationBadge verification={null} />)
    expect(container.innerHTML).toBe('')
  })

  it('opens on click with accessible wiring and lists every check with its status', () => {
    render(<VerificationBadge verification={v({ items_verified: 2, items_total: 5 })} />)
    expect(button().getAttribute('aria-expanded')).toBe('false')
    expect(popover()).toBeNull()
    act(() => button().click())
    expect(button().getAttribute('aria-expanded')).toBe('true')
    expect(button().getAttribute('aria-controls')).toBe(popover().id)
    const text = popover().textContent
    expect(text).toContain('Matches our reference table')
    expect(text).toContain('Prices are estimates')
    expect(text).toContain('Passed')
    expect(text).toContain('Note')
    expect(text).toContain('Failed')
    expect(text).toContain('2 of 5 items found online')
    expect(document.activeElement).toBe(popover())
  })

  it('links only http(s) sources', () => {
    render(<VerificationBadge verification={v()} />)
    act(() => button().click())
    const links = [...popover().querySelectorAll('a')]
    expect(links).toHaveLength(1)
    expect(links[0].getAttribute('href')).toBe('https://example.gov/visa')
    expect(links[0].getAttribute('rel')).toContain('noopener')
  })

  it('closes on Escape and returns focus to the chip', () => {
    render(<VerificationBadge verification={v()} />)
    act(() => button().click())
    key(popover(), 'Escape')
    expect(popover()).toBeNull()
    expect(document.activeElement).toBe(button())
  })

  it('closes on an outside press and on a second click of the chip', () => {
    render(<VerificationBadge verification={v()} />)
    act(() => button().click())
    act(() => { document.body.dispatchEvent(new MouseEvent('mousedown', { bubbles: true })) })
    expect(popover()).toBeNull()
    act(() => button().click())
    act(() => button().click())
    expect(popover()).toBeNull()
  })

  it('tabbing past the last link closes it and returns focus to the chip', () => {
    render(<VerificationBadge verification={v()} />)
    act(() => button().click())
    popover().querySelector('a').focus()
    key(popover().querySelector('a'), 'Tab')
    expect(popover()).toBeNull()
    expect(document.activeElement).toBe(button())
  })

  it('does not toggle a parent click handler', () => {
    let clicks = 0
    render(<div onClick={() => { clicks += 1 }}><VerificationBadge verification={v()} /></div>)
    act(() => button().click())
    expect(clicks).toBe(0)
  })

  it('survives a malformed checks field', () => {
    render(<VerificationBadge verification={v({ checks: null })} />)
    act(() => button().click())
    expect(popover().textContent).toContain('Matches our reference table.')
  })
})

describe('VerificationConflictBanner / FoundOnlineBadge', () => {
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

  it('banner shows the summary and the official link only for conflicts', () => {
    const conflict = v({
      level: 'conflict',
      label: 'Check details',
      summary: 'AI says e-visa; our reference table says visa-free. Check the official site.',
      checks: [{ label: 'Official', status: 'fail', detail: '', url: 'https://official.gov/x' }],
    })
    act(() => root.render(<VerificationConflictBanner verification={conflict} />))
    expect(container.textContent).toContain('AI says e-visa')
    expect(container.querySelector('a').getAttribute('href')).toBe('https://official.gov/x')
    expect(container.querySelector('[role="alert"]').className).toContain('rose')
    act(() => root.render(<VerificationConflictBanner verification={v()} />))
    expect(container.innerHTML).toBe('')
  })

  it('found-online badge only when link_verified is exactly true', () => {
    act(() => root.render(<FoundOnlineBadge item={{ link_verified: true }} />))
    expect(container.textContent).toContain('Found online')
    expect(container.querySelector('span').className).toContain('emerald')
    for (const item of [{ link_verified: false }, {}, { link_verified: 'yes' }, null]) {
      act(() => root.render(<FoundOnlineBadge item={item} />))
      expect(container.innerHTML).toBe('')
    }
  })
})
