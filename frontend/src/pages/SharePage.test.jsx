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
