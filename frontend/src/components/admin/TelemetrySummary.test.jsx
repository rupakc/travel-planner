// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import TelemetrySummary, { fillDays } from './TelemetrySummary'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

const NOW = new Date('2026-11-10T15:00:00Z')
const summary = {
  days: [
    { day: '2026-11-08', users: 4, sessions: 6, events: 30 },
    { day: '2026-11-09', users: 10, sessions: 12, events: 80 },
    { day: '2026-11-10', users: 3, sessions: 5, events: 20 },
  ],
  top_events: [{ event: 'app_open', events: 42 }, { event: 'screen_view', events: 7 }],
  top_screens: [{ route: '/chat', views: 9 }],
}

describe('fillDays', () => {
  it('returns one entry per day ending today, zero for missing days', () => {
    const out = fillDays(summary.days, 30, NOW)
    expect(out).toHaveLength(30)
    expect(out[29]).toEqual({ day: '2026-11-10', users: 3, sessions: 5, events: 20 })
    expect(out[0].day).toBe('2026-10-12')
    expect(out[0].users).toBe(0)
  })
})

describe('TelemetrySummary', () => {
  let container, root
  const render = (ui) => act(() => root.render(ui))
  beforeEach(() => {
    vi.useFakeTimers({ toFake: ['Date'] })
    vi.setSystemTime(NOW)
    container = document.createElement('div')
    document.body.appendChild(container)
    root = createRoot(container)
  })
  afterEach(() => {
    act(() => root.unmount())
    container.remove()
    vi.useRealTimers()
  })

  it('renders the stat tiles from the summary', () => {
    render(<TelemetrySummary summary={summary} />)
    expect(container.querySelector('[data-tid="admin.telemetry-users-today"]').textContent).toContain('3')
    expect(container.querySelector('[data-tid="admin.telemetry-sessions-today"]').textContent).toContain('5')
    expect(container.querySelector('[data-tid="admin.telemetry-users-7d"]').textContent).toContain('17')
  })

  it('renders an accessible chart and both tables', () => {
    render(<TelemetrySummary summary={summary} />)
    const svg = container.querySelector('svg[role="img"]')
    expect(svg.querySelector('title').textContent).toContain('Daily users')
    expect(svg.getAttribute('aria-labelledby')).toBeTruthy()
    expect(svg.querySelector('desc').textContent).toContain('Peak: 10')
    expect(container.textContent).toContain('app_open')
    expect(container.textContent).toContain('/chat')
  })

  it('shows an inline error when the call failed', () => {
    render(<TelemetrySummary error={new Error('boom')} />)
    expect(container.querySelector('[role="alert"]').textContent).toContain('Couldn')
  })

  it('shows loading without data', () => {
    render(<TelemetrySummary />)
    expect(container.textContent).toContain('Loading analytics')
  })
})
