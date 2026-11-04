// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { act } from 'react'
import { createRoot } from 'react-dom/client'

vi.mock('../../services/api', () => ({ extractImport: vi.fn() }))
vi.mock('../../utils/analytics', () => ({ track: vi.fn() }))

import { extractImport } from '../../services/api'
import { track } from '../../utils/analytics'
import ImportPanel from './ImportPanel'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

const PREVIEW = { title: 'T', places: [{ id: 'p1' }], destinations: [] }

function setValue(el, value) {
  const setter = Object.getOwnPropertyDescriptor(Object.getPrototypeOf(el), 'value').set
  act(() => {
    setter.call(el, value)
    el.dispatchEvent(new Event('input', { bubbles: true }))
  })
}

describe('ImportPanel', () => {
  let container, root, onPreview
  const render = (props = {}) => act(() => root.render(
    <ImportPanel token="tok" onPreview={onPreview} {...props} />,
  ))
  const textarea = () => container.querySelector('textarea')
  const submit = () => container.querySelector('button[type="submit"]')
  const byText = (text) => [...container.querySelectorAll('button')].find((b) => b.textContent.includes(text))

  beforeEach(() => {
    vi.useFakeTimers()
    container = document.createElement('div')
    document.body.appendChild(container)
    root = createRoot(container)
    onPreview = vi.fn()
    extractImport.mockReset()
    track.mockReset()
  })
  afterEach(() => {
    act(() => root.unmount())
    container.remove()
    vi.useRealTimers()
  })

  it('tells a link from text as the traveller types', () => {
    render()
    expect(submit().disabled).toBe(true)
    setValue(textarea(), 'https://blog.example/lisbon')
    expect(container.textContent).toContain("we'll read the page")
    setValue(textarea(), 'Belém Tower, LX Factory and Time Out Market')
    expect(container.textContent).toContain("we'll pick out the places")
    expect(submit().disabled).toBe(false)
  })

  it('fills an example and sends it as text', async () => {
    let resolve
    extractImport.mockReturnValue(new Promise((r) => { resolve = r }))
    render()
    act(() => byText('48 hours in Lisbon').click())
    expect(textarea().value).toContain('Time Out Market')
    act(() => submit().click())
    expect(extractImport).toHaveBeenCalledWith(
      { text: expect.stringContaining('Time Out Market') }, 'tok', expect.any(AbortSignal),
    )
    expect(track).toHaveBeenCalledWith('import_started', 'search', { kind: 'text' })
    await act(async () => { resolve(PREVIEW) })
    expect(onPreview).toHaveBeenCalledWith(PREVIEW)
  })

  it('tells the story while it works and can be cancelled with Esc', async () => {
    extractImport.mockImplementation((_b, _t, signal) => new Promise((_r, reject) => {
      signal.addEventListener('abort', () => reject(Object.assign(new Error('canceled'), { name: 'CanceledError', code: 'ERR_CANCELED' })))
    }))
    render()
    setValue(textarea(), 'https://blog.example/lisbon')
    act(() => submit().click())
    const live = container.querySelector('[aria-live="polite"]')
    expect(live.textContent).toContain('Reading the page')
    act(() => vi.advanceTimersByTime(3000))
    expect(live.textContent).toContain('Finding places')
    act(() => vi.advanceTimersByTime(6000))
    expect(live.textContent).toContain('Putting them on the map')
    await act(async () => {
      document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))
    })
    expect(container.querySelector('[aria-live="polite"]')).toBeNull()
    expect(textarea().value).toBe('https://blog.example/lisbon')
    expect(onPreview).not.toHaveBeenCalled()
  })

  it('turns a blocked source into a one-click switch', async () => {
    extractImport.mockRejectedValue({
      response: { status: 422, data: { detail: { code: 'blocked_source', message: "Instagram doesn't let apps read posts. Paste the caption or drop a screenshot instead." } } },
    })
    render()
    setValue(textarea(), 'https://www.instagram.com/p/abc/')
    await act(async () => { submit().click() })
    const alert = container.querySelector('[role="alert"]')
    expect(alert.textContent).toContain('Instagram')
    expect(track).toHaveBeenCalledWith('import_failed', 'search', { code: 'blocked_source' })
    act(() => byText('Paste the text').click())
    expect(textarea().value).toBe('')
    expect(document.activeElement).toBe(textarea())
    expect(container.querySelector('[role="alert"]')).toBeNull()
  })

  it('explains screenshots it cannot use', async () => {
    render()
    const input = container.querySelector('input[type="file"]')
    const heic = new File(['x'], 'IMG_0001.HEIC', { type: 'image/heic' })
    await act(async () => {
      Object.defineProperty(input, 'files', { value: [heic], configurable: true })
      input.dispatchEvent(new Event('change', { bubbles: true }))
    })
    expect(container.textContent).toMatch(/HEIC/)
    expect(container.querySelectorAll('[data-shot]')).toHaveLength(0)
  })

  it('starts by itself for a deep link', async () => {
    extractImport.mockResolvedValue(PREVIEW)
    await act(async () => { render({ seed: { url: 'https://blog.example/a', autoStart: true, nonce: 1 } }) })
    expect(extractImport).toHaveBeenCalledWith({ url: 'https://blog.example/a' }, 'tok', expect.any(AbortSignal))
    expect(onPreview).toHaveBeenCalledWith(PREVIEW)
  })
})
