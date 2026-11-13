// @vitest-environment jsdom
// An OAuth account whose (untrusted) provider email isn't verified yet has
// `User.email: null` until the verify link is redeemed. No section may crash
// or print "null".
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { MemoryRouter } from 'react-router-dom'

const USER = {
  id: 'u1', username: 'gh_jane', display_name: 'Jane', email: null, email_verified: false,
  is_admin: false, requires_password_change: false, account_verified: false, has_password: false,
  signup_method: 'oauth', avatar_url: null,
}
const auth = { token: 'tok', user: USER, accountVerified: false, logout: vi.fn(), refreshUser: vi.fn(), updateTokenAfterPasswordChange: vi.fn() }
vi.mock('../../context/AuthContext', () => ({ useAuth: () => auth, useOptionalAuth: () => auth }))
vi.mock('../../services/api', () => ({ getAuthProviders: vi.fn(async () => []) }))
vi.mock('../../services/authApi', () => ({ getLinkTicket: vi.fn(), changePassword: vi.fn(), logoutAll: vi.fn(), listSessions: vi.fn().mockRejectedValue({ status: 404 }), revokeSession: vi.fn() }))
vi.mock('../../services/accountApi', () => ({
  unlinkIdentity: vi.fn(), requestEmailVerification: vi.fn(), updateProfile: vi.fn(), uploadAvatar: vi.fn(),
  removeAvatar: vi.fn(), exportAccount: vi.fn(), deleteAccount: vi.fn(),
}))
vi.mock('../../telemetry/client', () => ({ emit: vi.fn() }))

import { initI18n } from '../../i18n/index'
import ProfileSection from './ProfileSection'
import SecuritySection from './SecuritySection'
import DataSection from './DataSection'
import AccountMenu from './AccountMenu'
import VerifyBanner from './VerifyBanner'
import { requestEmailVerification } from '../../services/accountApi'

globalThis.IS_REACT_ACT_ENVIRONMENT = true
let container, root
beforeEach(async () => {
  await initI18n({ lng: 'en' })
  try { sessionStorage.clear() } catch { /* */ }
  container = document.createElement('div'); document.body.appendChild(container); root = createRoot(container)
})
afterEach(() => { act(() => root.unmount()); container.remove() })
const tid = (id) => container.querySelector(`[data-tid="${id}"]`)
const account = { user: USER, identities: [{ provider: 'github', email: null, linked_at: '2026-11-11T10:00:00Z' }], settings: {}, onboarding: {} }

describe('email: null', () => {
  it('renders every account section without "null"', async () => {
    await act(async () => root.render(
      <MemoryRouter>
        <AccountMenu />
        <VerifyBanner />
        <ProfileSection account={account} reload={vi.fn()} />
        <SecuritySection account={account} reload={vi.fn()} />
        <DataSection account={account} />
      </MemoryRouter>,
    ))
    expect(container.textContent).not.toMatch(/\bnull\b|undefined/)
    expect(tid('profile.section')).not.toBeNull()
    expect(tid('account.data')).not.toBeNull()
  })

  it('Profile shows a neutral "No email yet" line', async () => {
    await act(async () => root.render(<ProfileSection account={account} reload={vi.fn()} />))
    expect(tid('profile.emailNone').textContent).toBe('No email yet')
    expect(tid('profile.email')).toBeNull()
  })

  it('the verify banner keeps "Send link" (the server re-sends to the pending address)', async () => {
    requestEmailVerification.mockResolvedValueOnce({ status: 'verification_sent', email: 'j@x.io', expires_in: 1800 })
    await act(async () => root.render(<VerifyBanner />))
    expect(tid('verify-banner.send')).not.toBeNull()
    await act(async () => tid('verify-banner.send').click())
    expect(requestEmailVerification).toHaveBeenCalledWith('tok')
    expect(tid('verify-banner.text').textContent).toMatch(/sent|link/i)
  })

  it('on 422 no_email it shows the errors text and hides the button', async () => {
    requestEmailVerification.mockRejectedValueOnce({ status: 422, code: 'no_email', detail: 'x' })
    await act(async () => root.render(<VerifyBanner />))
    await act(async () => tid('verify-banner.send').click())
    expect(tid('verify-banner.error').textContent).toBe('Your account has no email address.')
    expect(tid('verify-banner.send')).toBeNull()
  })
})
