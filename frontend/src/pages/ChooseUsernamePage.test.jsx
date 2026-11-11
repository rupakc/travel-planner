// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { MemoryRouter, Routes, Route, useLocation } from 'react-router-dom'

const completeOAuthSignup = vi.fn()
vi.mock('../services/authApi', () => ({ completeOAuthSignup: (...a) => completeOAuthSignup(...a) }))
const applySession = vi.fn()
vi.mock('../context/AuthContext', () => ({ useAuth: () => ({ applySession }) }))
vi.mock('../telemetry/client', () => ({ emit: vi.fn() }))
const announceGame = vi.fn()
vi.mock('../game/announce', () => ({ announceGame: (...a) => announceGame(...a) }))
import '../i18n'
import ChooseUsernamePage from './ChooseUsernamePage'

globalThis.IS_REACT_ACT_ENVIRONMENT = true
let container, root, seen
function Probe() { seen = useLocation(); return null }
const oauth = { status: 'needs_username', signup_token: 'T', suggested_username: 'jane', display_name: 'Jane Doe', email: 'j@x.io', invite_required: false, return_to: '/chat' }
const mount = async (state) => act(async () => root.render(
  <MemoryRouter initialEntries={[{ pathname: '/auth/username', state }]}>
    <Routes>
      <Route path="/auth/username" element={<ChooseUsernamePage />} />
      <Route path="*" element={<Probe />} />
    </Routes>
  </MemoryRouter>))
const q = (tid) => container.querySelector(`[data-tid="${tid}"]`)
const setVal = async (el, v) => act(async () => {
  Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(el, v)
  el.dispatchEvent(new Event('input', { bubbles: true }))
})
const submit = async () => act(async () => { q('oauth.username.form').dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })) })

beforeEach(() => {
  container = document.createElement('div'); document.body.appendChild(container)
  root = createRoot(container)
  completeOAuthSignup.mockReset(); applySession.mockReset(); announceGame.mockReset(); seen = undefined
})
afterEach(() => { act(() => root.unmount()); container.remove() })

describe('ChooseUsernamePage', () => {
  it('prefills the suggestion and display name; no invite field unless required', async () => {
    await mount({ oauth })
    expect(q('oauth.username.input').value).toBe('jane')
    expect(q('oauth.username.display-name').value).toBe('Jane Doe')
    expect(q('oauth.username.invite')).toBeNull()
  })

  it('shows an invite field when required and sends the code', async () => {
    completeOAuthSignup.mockResolvedValue({ session: { access_token: 't' }, game: {} })
    await mount({ oauth: { ...oauth, invite_required: true } })
    await setVal(q('oauth.username.invite'), 'ABC')
    await submit()
    expect(completeOAuthSignup).toHaveBeenCalledWith(expect.objectContaining({ signup_token: 'T', username: 'jane', invite_code: 'ABC' }))
  })

  it('submits, adopts the session and returns to return_to', async () => {
    completeOAuthSignup.mockResolvedValue({ session: { access_token: 't' }, game: { awards: [1] } })
    await mount({ oauth })
    await setVal(q('oauth.username.input'), 'jane_d')
    await submit()
    expect(completeOAuthSignup).toHaveBeenCalledWith({ signup_token: 'T', username: 'jane_d', display_name: 'Jane Doe' })
    expect(applySession).toHaveBeenCalledWith({ access_token: 't' })
    expect(announceGame).toHaveBeenCalled()
    expect(seen.pathname).toBe('/chat')
  })

  it('shows the translated error for a taken username and stays', async () => {
    completeOAuthSignup.mockRejectedValue({ status: 409, code: 'username_taken', detail: '' })
    await mount({ oauth })
    await submit()
    expect(q('oauth.username.error').textContent).toBe('That username is taken.')
    expect(seen).toBeUndefined()
  })

  it('a reload (no router state) goes back to /login with "Please start again"', async () => {
    await mount(undefined)
    expect(seen.pathname).toBe('/login')
    expect(seen.state.notice).toBe('Please start again.')
  })
})
