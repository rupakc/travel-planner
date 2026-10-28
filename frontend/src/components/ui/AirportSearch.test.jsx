// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import AirportSearch from './AirportSearch'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

describe('AirportSearch', () => {
  let container, root

  const render = (props) => act(() => root.render(<AirportSearch onChange={() => {}} {...props} />))
  const input = () => container.querySelector('input')

  beforeEach(() => {
    container = document.createElement('div')
    document.body.appendChild(container)
    root = createRoot(container)
  })

  afterEach(() => {
    act(() => root.unmount())
    container.remove()
    vi.useRealTimers()
    vi.unstubAllGlobals()
  })

  it('shows a value set from outside after mount (e.g. a loaded recent search)', () => {
    render({ value: '' })
    render({ value: 'Lisbon, Portugal (LIS)' })
    expect(input().value).toBe('Lisbon, Portugal (LIS)')
  })

  it('clears when the value is cleared from outside', () => {
    render({ value: 'Lisbon, Portugal (LIS)' })
    render({ value: '' })
    expect(input().value).toBe('')
  })

  it('keeps the friendly label after picking an airport, even though only the code is stored', async () => {
    vi.useFakeTimers()
    vi.stubGlobal('fetch', vi.fn(async () => ({
      json: async () => [{ iata_code: 'LIS', city: 'Lisbon', country: 'Portugal', name: 'Humberto Delgado' }],
    })))
    // A controlled parent: whatever the component emits becomes its value
    let value = ''
    const onChange = (v) => { value = v; render({ value, onChange }) }
    render({ value, onChange })

    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set
    act(() => {
      setter.call(input(), 'Lisb')
      input().dispatchEvent(new Event('input', { bubbles: true }))
    })
    await act(async () => { await vi.advanceTimersByTimeAsync(300) })

    const option = [...container.querySelectorAll('li button')][0]
    act(() => option.dispatchEvent(new MouseEvent('mousedown', { bubbles: true })))

    expect(value).toBe('LIS')
    expect(input().value).toBe('LIS — Lisbon, Portugal')
  })
})
