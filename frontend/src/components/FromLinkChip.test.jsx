// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach } from 'vitest'
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import FromLinkChip, { InspiredBy } from './FromLinkChip'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

describe('FromLinkChip', () => {
  let container, root
  const render = (ui) => act(() => root.render(ui))
  beforeEach(() => {
    container = document.createElement('div')
    document.body.appendChild(container)
    root = createRoot(container)
  })
  afterEach(() => {
    act(() => root.unmount())
    container.remove()
  })

  it('shows the label and reveals the quote on tap', () => {
    render(<FromLinkChip quote="go at dawn" note="Quietest before 8am" />)
    const btn = container.querySelector('button')
    expect(btn.textContent).toContain('From your link')
    expect(btn.getAttribute('aria-expanded')).toBe('false')
    act(() => btn.click())
    expect(btn.getAttribute('aria-expanded')).toBe('true')
    expect(container.textContent).toContain('“go at dawn”')
    expect(container.textContent).toContain('Quietest before 8am')
  })

  it('is a plain label when there is nothing to reveal', () => {
    render(<FromLinkChip />)
    expect(container.querySelector('button')).toBeNull()
    expect(container.textContent).toContain('From your link')
  })
})

describe('InspiredBy', () => {
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

  it('links a safe source URL', () => {
    act(() => root.render(<InspiredBy source={{ url: 'https://blog.example/x', title: '48h in Lisbon' }} />))
    const a = container.querySelector('a')
    expect(a.href).toBe('https://blog.example/x')
    expect(a.rel).toContain('noopener')
    expect(container.textContent).toContain('Inspired by')
    expect(container.textContent).toContain('48h in Lisbon')
  })

  it('never links an unsafe URL', () => {
    act(() => root.render(<InspiredBy source={{ url: 'javascript:alert(1)', title: 'Notes' }} />))
    expect(container.querySelector('a')).toBeNull()
    expect(container.textContent).toContain('Notes')
  })

  it('renders nothing without a source', () => {
    act(() => root.render(<InspiredBy source={null} />))
    expect(container.textContent).toBe('')
  })
})
