// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { MemoryRouter, Routes, Route } from 'react-router-dom'

const auth = { token: 'tok', logout: vi.fn(), updateTokenAfterPasswordChange: vi.fn() }
vi.mock('../../context/AuthContext', () => ({ useAuth: () => auth }))
vi.mock('../../services/api', () => ({ getAuthProviders: vi.fn() }))
vi.mock('../../services/authApi', () => ({
  getLinkStartUrl: vi.fn(), logoutAll: vi.fn(), changePasswordV2: vi.fn(),
  listSessions: vi.fn(), revokeSession: vi.fn(),
}))
vi.mock('../../services/accountApi', () => ({ unlinkIdentity: vi.fn(), requestEmailVerification: vi.fn() }))
vi.mock('../auth/navigate', () => ({ navigateTo: vi.fn() }))
vi.mock('../auth/PasswordStrengthMeter', () => ({ default: () => null }))

import SecuritySection from './SecuritySection'
import { getAuthProviders } from '../../services/api'
import { getLinkStartUrl, logoutAll, changePasswordV2, listSessions, revokeSession } from '../../services/authApi'
import { unlinkIdentity } from '../../services/accountApi'
import { navigateTo } from '../auth/navigate'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

let container, root
const account = (over = {}) => ({
  user: { username: 'jo', email: 'jo@example.com', email_verified: true, has_password: true, ...over.user },
  identities: over.identities || [],
})
const reload = vi.fn()
const render = async (acc = account()) => act(async () => root.render(
  <MemoryRouter initialEntries={['/account']}>
    <Routes>
      <Route path="/account" element={<SecuritySection account={acc} reload={reload} />} />
      <Route path="/login" element={<p data-tid="login-page">login</p>} />
    </Routes>
  </MemoryRouter>,
))
const tid = (id) => container.querySelector(`[data-tid="${id}"]`)
const click = async (el) => act(async () => { el.dispatchEvent(new MouseEvent('click', { bubbles: true })) })

beforeEach(() => {
  vi.clearAllMocks()
  listSessions.mockRejectedValue({ status: 404 })
  getAuthProviders.mockResolvedValue([{ id: 'github', configured: true, start_url: '/api/auth/oauth/github/start' }])
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
})
afterEach(() => { act(() => root.unmount()); container.remove() })

describe('SecuritySection', () => {
  it('renders nothing without an account', async () => {
    await act(async () => root.render(<MemoryRouter><SecuritySection account={null} /></MemoryRouter>))
    expect(container.innerHTML).toBe('')
  })

  it('shows the four providers in order with connected state', async () => {
    await render(account({ identities: [{ provider: 'google', email: 'g@x.com' }] }))
    const ids = [...container.querySelectorAll('[data-tid^="security.provider."]')].map((e) => e.dataset.tid)
    expect(ids).toEqual(['apple', 'google', 'facebook', 'github'].map((p) => `security.provider.${p}`))
    expect(tid('security.provider.google').textContent).toContain('Connected as g@x.com')
    expect(tid('security.disconnect.google')).not.toBeNull()
    expect(tid('security.connect.github')).not.toBeNull()
  })

  it('Connect navigates to a same-origin /api/auth/ start path', async () => {
    getLinkStartUrl.mockResolvedValue({ start_url: '/api/auth/oauth/github/start?link=t&client=web' })
    await render()
    await click(tid('security.connect.github'))
    expect(getLinkStartUrl).toHaveBeenCalledWith('tok', 'github')
    expect(navigateTo).toHaveBeenCalledWith('/api/auth/oauth/github/start?link=t&client=web')
  })

  it.each(['https://evil.example/api/auth/x', '/other/path', '/api/auth/../x'])('does not navigate to %s', async (u) => {
    getLinkStartUrl.mockResolvedValue({ start_url: u })
    await render()
    await click(tid('security.connect.github'))
    expect(navigateTo).not.toHaveBeenCalled()
  })

  it('an unconfigured provider shows coming soon without calling the API', async () => {
    await render()
    await click(tid('security.connect.apple'))
    expect(getLinkStartUrl).not.toHaveBeenCalled()
    expect(tid('security.provider-msg').textContent).toMatch(/Apple sign-in is coming soon/)
  })

  it('Disconnect with 409 last_sign_in_method shows the set-password hint', async () => {
    unlinkIdentity.mockRejectedValue({ status: 409, code: 'last_sign_in_method', detail: '' })
    await render(account({ identities: [{ provider: 'google', email: 'g@x.com' }] }))
    await click(tid('security.disconnect.google'))
    expect(tid('security.provider-msg').textContent).toMatch(/Set a password first/)
    expect(reload).not.toHaveBeenCalled()
  })

  it('Disconnect success reloads the account', async () => {
    unlinkIdentity.mockResolvedValue(null)
    await render(account({ identities: [{ provider: 'google', email: 'g@x.com' }] }))
    await click(tid('security.disconnect.google'))
    expect(unlinkIdentity).toHaveBeenCalledWith('tok', 'google')
    expect(reload).toHaveBeenCalled()
  })

  it('shows Verify email only when unverified', async () => {
    await render()
    expect(tid('security.verify-email')).toBeNull()
    await render(account({ user: { email_verified: false } }))
    expect(tid('security.verify-email')).not.toBeNull()
  })

  it('without a password there is no current-password field and an empty current is sent', async () => {
    changePasswordV2.mockResolvedValue({ access_token: 'new' })
    await render(account({ user: { has_password: false } }))
    expect(tid('security.current-password')).toBeNull()
    const input = tid('security.new-password')
    await act(async () => {
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(input, 'a-long-passphrase-1')
      input.dispatchEvent(new Event('input', { bubbles: true }))
    })
    await act(async () => { tid('security.password-form').dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })) })
    expect(changePasswordV2).toHaveBeenCalledWith('tok', '', 'a-long-passphrase-1')
    expect(auth.updateTokenAfterPasswordChange).toHaveBeenCalledWith('new')
    // The refresh comes from the token change (AccountPage reloads with the new
    // token); an immediate reload() would use the revoked one.
    expect(reload).not.toHaveBeenCalled()
  })

  it('Sign out everywhere confirms, logs out locally and goes to /login', async () => {
    logoutAll.mockResolvedValue(null)
    await render()
    await click(tid('security.logout-all'))
    expect(logoutAll).not.toHaveBeenCalled()
    await click(tid('security.logout-all-confirm'))
    expect(logoutAll).toHaveBeenCalledWith('tok')
    expect(auth.logout).toHaveBeenCalled()
    expect(tid('login-page')).not.toBeNull()
  })
})

describe('SecuritySection password refresh', () => {
  it('reloads only when no new token came back', async () => {
    changePasswordV2.mockResolvedValue({})
    await render(account({ user: { has_password: false } }))
    const input = tid('security.new-password')
    await act(async () => {
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(input, 'a-long-passphrase-1')
      input.dispatchEvent(new Event('input', { bubbles: true }))
    })
    await act(async () => { tid('security.password-form').dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })) })
    expect(auth.updateTokenAfterPasswordChange).not.toHaveBeenCalled()
    expect(reload).toHaveBeenCalledTimes(1)
  })

  describe('signed-in devices', () => {
    const devs = [
      { id: 'a', client: 'android', device_name: 'Pixel 8', last_used_at: new Date().toISOString(), current: true },
      { id: 'b', client: 'ios', device_name: null, last_used_at: new Date(Date.now() - 3 * 3600e3).toISOString(), current: false },
    ]
    it('hides the list on an older backend (404)', async () => {
      await render()
      expect(tid('security.device')).toBeNull()
    })
    it('lists devices, offers sign-out only for the others, and removes one on success', async () => {
      listSessions.mockResolvedValue({ sessions: devs })
      revokeSession.mockResolvedValue(null)
      await render()
      expect(container.querySelectorAll('[data-tid="security.device"]').length).toBe(2)
      const outs = container.querySelectorAll('[data-tid="security.device-signout"]')
      expect(outs.length).toBe(1)
      await click(outs[0])
      expect(revokeSession).toHaveBeenCalledWith('tok', 'b')
      expect(container.querySelectorAll('[data-tid="security.device"]').length).toBe(1)
    })
    it('shows an error when revoking fails', async () => {
      listSessions.mockResolvedValue({ sessions: devs })
      revokeSession.mockRejectedValue({ status: 500 })
      await render()
      await click(tid('security.device-signout'))
      expect(tid('security.device-msg')).not.toBeNull()
      expect(container.querySelectorAll('[data-tid="security.device"]').length).toBe(2)
    })
  })
})
