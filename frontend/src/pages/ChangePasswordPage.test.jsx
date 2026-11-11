// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { MemoryRouter } from 'react-router-dom'

const auth = { token: 't', user: { username: 'jane' }, updateTokenAfterPasswordChange: vi.fn() }
vi.mock('../context/AuthContext', () => ({ useAuth: () => auth }))
vi.mock('../components/ui/AttributionFooter', () => ({ default: () => null }))

import ChangePasswordPage from './ChangePasswordPage'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

let container, root
const q = (tid) => container.querySelector(`[data-tid="${tid}"]`)
const setVal = async (el, v) => act(async () => {
  Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(el, v)
  el.dispatchEvent(new Event('input', { bubbles: true }))
})
const submit = async () => act(async () => {
  container.querySelector('form').dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }))
})
async function fill(next) {
  await setVal(q('change-password.temporary'), 'temp-pass-1')
  await setVal(q('change-password.new'), next)
  await setVal(q('change-password.confirm'), next)
}

beforeEach(async () => {
  vi.stubGlobal('fetch', vi.fn())
  container = document.createElement('div'); document.body.appendChild(container)
  root = createRoot(container)
  await act(async () => root.render(<MemoryRouter><ChangePasswordPage /></MemoryRouter>))
})
afterEach(() => { act(() => root.unmount()); container.remove(); vi.unstubAllGlobals() })

describe('ChangePasswordPage', () => {
  it('says and enforces 10 characters, the server minimum', async () => {
    expect(q('change-password.new').getAttribute('placeholder')).toBe('At least 10 characters')
    expect(q('change-password.new').getAttribute('minlength')).toBe('10')
    await fill('nine-char')
    await submit()
    expect(fetch).not.toHaveBeenCalled()
    expect(container.textContent).toContain('Password must be at least 10 characters')
  })

  it('shows the translated error_code from the server', async () => {
    fetch.mockResolvedValue(new Response(JSON.stringify({ detail: 'Password is in the common list', error_code: 'password_common' }), { status: 400 }))
    await fill('password1234')
    await submit()
    expect(container.textContent).toContain('That password is too common. Choose a less guessable one.')
  })
})
