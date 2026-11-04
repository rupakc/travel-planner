// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import AlertEmailField, { isEmail } from './AlertEmailField'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

describe('isEmail', () => {
  it.each([
    ['a@b.co', true], ['first.last@mail.example.org', true],
    ['nope', false], ['a@b', false], ['a b@c.de', false], ['@x.com', false], ['x@.com', false],
  ])('%s → %s', (v, ok) => expect(isEmail(v)).toBe(ok))
})

describe('AlertEmailField', () => {
  let container, root
  const setValue = (input, value) => {
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set
    setter.call(input, value)
    input.dispatchEvent(new Event('input', { bubbles: true }))
  }
  const render = (props) => act(() => root.render(<AlertEmailField {...props} />))
  const input = () => container.querySelector('input[type="email"]')
  const save = () => [...container.querySelectorAll('button')].find(b => b.textContent.includes('Save'))

  beforeEach(() => {
    container = document.createElement('div')
    document.body.appendChild(container)
    root = createRoot(container)
  })
  afterEach(() => { act(() => root.unmount()); container.remove() })

  it('saves a valid address and reports back', async () => {
    const onSave = vi.fn().mockResolvedValue({ email: 'me@trip.test' })
    const onSaved = vi.fn()
    render({ email: null, emailAlertsAvailable: true, onSave, onSaved })
    act(() => setValue(input(), ' Me@Trip.test '))
    await act(async () => save().click())
    expect(onSave).toHaveBeenCalledWith('Me@Trip.test')
    expect(onSaved).toHaveBeenCalledWith('me@trip.test')
    expect(container.textContent).toContain('Saved')
  })

  it('blocks an invalid address with a clear message', async () => {
    const onSave = vi.fn()
    render({ email: null, emailAlertsAvailable: true, onSave })
    act(() => setValue(input(), 'not-an-email'))
    await act(async () => save().click())
    expect(onSave).not.toHaveBeenCalled()
    expect(container.querySelector('[role="alert"]').textContent).toMatch(/email address/)
    expect(input().getAttribute('aria-invalid')).toBe('true')
  })

  it('shows the server’s message (e.g. already in use)', async () => {
    const err = { response: { status: 409, data: { detail: 'Another account already uses that email.' } } }
    render({ email: null, emailAlertsAvailable: true, onSave: vi.fn().mockRejectedValue(err) })
    act(() => setValue(input(), 'taken@trip.test'))
    await act(async () => save().click())
    expect(container.textContent).toContain('Another account already uses that email.')
  })

  it('explains when the server cannot send email', () => {
    render({ email: 'me@trip.test', emailAlertsAvailable: false, onSave: vi.fn() })
    expect(container.textContent).toMatch(/isn’t sending email/)
    expect(input().value).toBe('me@trip.test')
  })
})
