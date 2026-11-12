// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import SharePage from './SharePage'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

const PLAN = { name: 'Trip', search_data: { destination: 'Lisbon', num_travelers: 1 }, selections: {} }
const flush = () => act(async () => { await new Promise((r) => setTimeout(r, 0)) })

describe('SharePage download', () => {
  let container, root
  beforeEach(async () => {
    globalThis.fetch = vi.fn(() => Promise.resolve({ ok: true, json: () => Promise.resolve(PLAN) }))
    container = document.createElement('div')
    document.body.appendChild(container)
    root = createRoot(container)
  })
  afterEach(() => {
    act(() => root.unmount())
    container.remove()
  })

  const mount = async (download) => {
    await act(async () => {
      root.render(
        <MemoryRouter initialEntries={['/share/abc']}>
          <Routes><Route path="/share/:token" element={<SharePage download={download} />} /></Routes>
        </MemoryRouter>,
      )
    })
    await flush()
  }
  const button = () => container.querySelector('[data-tid="share.download"]')

  it('ignores a second click while the first download is still running', async () => {
    let finish
    const download = vi.fn(() => new Promise((resolve) => { finish = resolve }))
    await mount(download)
    await act(async () => { button().click(); button().click() })
    expect(download).toHaveBeenCalledTimes(1)
    expect(button().disabled).toBe(true)
    expect(button().getAttribute('aria-busy')).toBe('true')
    await act(async () => { finish() })
    expect(button().disabled).toBe(false)
    await act(async () => { button().click() })
    expect(download).toHaveBeenCalledTimes(2)
  })

  it('shows an inline error when the download throws, and clears it on retry', async () => {
    const download = vi.fn()
      .mockRejectedValueOnce(new Error('boom'))
      .mockResolvedValueOnce(undefined)
    await mount(download)
    await act(async () => { button().click() })
    expect(container.querySelector('[role="alert"]').textContent).toBe('Couldn’t create the trip card. Please try again.')
    expect(button().disabled).toBe(false)
    await act(async () => { button().click() })
    expect(container.querySelector('[role="alert"]')).toBeNull()
  })
})

describe('SharePage privacy choices', () => {
  let container, root
  afterEach(() => { act(() => root.unmount()); container.remove() })

  it.each([
    ['a shared plan', () => Promise.resolve({ ok: true, json: () => Promise.resolve(PLAN) })],
    ['a missing plan', () => Promise.resolve({ ok: false, status: 404, json: () => Promise.resolve({}) })],
  ])('offers the footer "Privacy choices" button on %s', async (_label, respond) => {
    globalThis.fetch = vi.fn(respond)
    container = document.createElement('div')
    document.body.appendChild(container)
    root = createRoot(container)
    await act(async () => {
      root.render(
        <MemoryRouter initialEntries={['/share/abc']}>
          <Routes><Route path="/share/:token" element={<SharePage />} /></Routes>
        </MemoryRouter>,
      )
    })
    await flush()
    expect(container.querySelector('[data-tid="privacy.choices"]')).not.toBeNull()
  })
})

describe('SharePage kinds', () => {
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
  const show = async (body, ok = true) => {
    globalThis.fetch = vi.fn(() => Promise.resolve({ ok, json: () => Promise.resolve(body) }))
    await act(async () => {
      root.render(
        <MemoryRouter initialEntries={['/share/abc']}>
          <Routes><Route path="/share/:token" element={<SharePage />} /></Routes>
        </MemoryRouter>,
      )
    })
    await flush()
  }
  const text = () => container.textContent

  it('sets robots noindex while mounted and removes it on unmount', async () => {
    await show(PLAN)
    expect(document.head.querySelector('meta[name="robots"][content="noindex"]')).toBeTruthy()
    act(() => root.unmount())
    expect(document.head.querySelector('meta[name="robots"]')).toBeNull()
    root = createRoot(container)
  })

  it('legacy response (no kind) renders the plan with no byline', async () => {
    await show({ ...PLAN, search_data: { destination: 'Lisbon', origin: 'NYC', departure_date: '2026-04-01', return_date: '2026-04-08', num_travelers: 2 } })
    expect(text()).toContain('Lisbon')
    expect(text()).toContain('NYC')
    expect(container.querySelector('[data-tid="share.byline"]')).toBeNull()
    expect(container.querySelector('[data-tid="share.plan-own"]')).toBeTruthy()
  })

  it('plan kind without dates or origin shows neither, with a byline when owner_name is present', async () => {
    await show({ ...PLAN, kind: 'plan', options: { dates: 'hidden' }, owner_name: 'Ana', search_data: { destination: 'Lisbon' } })
    expect(text()).not.toContain('From ')
    expect(container.querySelector('svg.lucide-calendar')).toBeNull()
    expect(container.querySelector('[data-tid="share.byline"]').textContent).toBe('Shared by Ana')
  })

  it('month-only dates render as month and year', async () => {
    await show({ ...PLAN, kind: 'plan', search_data: { destination: 'Lisbon', departure_date: '2026-04', return_date: '2026-04' } })
    expect(text()).toMatch(/Apr(il)? 2026/)
    expect(text()).not.toContain('Invalid')
  })

  it('recap renders the card with stats, destination and period', async () => {
    await show({
      name: 'T', kind: 'recap', search_data: {}, selections: {},
      card: { headline: 'My trip to Japan: recap', destination: 'Japan', period: '2026-04', stats: [{ key: 'places_visited', count: 7 }] },
    })
    expect(container.querySelector('h1').textContent).toBe('My trip to Japan: recap')
    expect(text()).toContain('Trip recap')
    expect(text()).toContain('7 Places visited')
    expect(text()).toContain('Japan')
    expect(text()).toMatch(/Apr(il)? 2026/)
    expect(container.querySelector('[data-tid="share.plan-own"]').textContent).toBe('Plan your own trip')
  })

  it('savings renders the card, and a card without optional parts does not crash', async () => {
    await show({ name: 'P', kind: 'savings', search_data: {}, selections: {}, card: { headline: 'Caught drops worth $120', stats: [] } })
    expect(text()).toContain('Price drops caught')
    expect(text()).toContain('Caught drops worth $120')
  })

  it('renders hostile text as text', async () => {
    await show({
      name: 'x', kind: 'recap', owner_name: '<b>evil</b>', search_data: {}, selections: {},
      card: { headline: '<script>alert(1)</script>', destination: '<img src=x onerror=alert(1)>', stats: [{ key: '<i>', count: 1 }] },
    })
    expect(container.querySelector('script, img, b, i')).toBeNull()
    expect(text()).toContain('<script>alert(1)</script>')
    expect(text()).toContain('Shared by <b>evil</b>')
  })

  it('emits share_view with the kind', async () => {
    const emit = vi.fn()
    vi.doMock('../telemetry/client', () => ({ emit }))
    await show({ name: 'T', kind: 'savings', search_data: {}, selections: {}, card: { headline: 'h', stats: [] } })
    await flush()
    expect(emit).toHaveBeenCalledWith('share_view', { kind: 'savings' })
    vi.doUnmock('../telemetry/client')
  })

  it('shows the unavailable state on a failed fetch', async () => {
    await show({}, false)
    expect(container.querySelector('[data-tid="share.plan-own-error"]')).toBeTruthy()
  })
})
