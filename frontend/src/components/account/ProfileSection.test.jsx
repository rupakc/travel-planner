// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { act } from 'react'
import { createRoot } from 'react-dom/client'

const refreshUser = vi.fn().mockResolvedValue(undefined)
vi.mock('../../context/AuthContext', () => ({
  useAuth: () => ({
    token: 'tok', refreshUser,
    user: { username: 'jane', display_name: 'Jane', email: 'j@x.io', email_verified: false, avatar_url: null },
  }),
}))
vi.mock('../../services/accountApi', () => ({
  updateProfile: vi.fn().mockResolvedValue({}), uploadAvatar: vi.fn(), removeAvatar: vi.fn(),
}))
vi.mock('../../telemetry/client', () => ({ emit: vi.fn() }))

import '../../i18n/index'
import { initI18n } from '../../i18n/index'
import { updateProfile, uploadAvatar } from '../../services/accountApi'
import ProfileSection from './ProfileSection'

globalThis.IS_REACT_ACT_ENVIRONMENT = true
let container, root
beforeEach(async () => {
  await initI18n({ lng: 'en' })
  vi.clearAllMocks()
  container = document.createElement('div'); document.body.appendChild(container); root = createRoot(container)
})
afterEach(() => { act(() => root.unmount()); container.remove() })
const tid = (id) => container.querySelector(`[data-tid="${id}"]`)

describe('ProfileSection', () => {
  it('shows identity from /auth/me with no edit controls when the account API is unavailable', () => {
    act(() => root.render(<ProfileSection account={null} />))
    expect(tid('profile.username').textContent).toBe('@jane')
    expect(tid('profile.email').textContent).toBe('j@x.io')
    expect(tid('profile.emailUnverified')).not.toBeNull()
    expect(tid('profile.avatarChange')).toBeNull()
    expect(tid('profile.nameEdit')).toBeNull()
  })

  it('saves a new name through updateProfile then refreshUser', async () => {
    const reload = vi.fn()
    act(() => root.render(<ProfileSection account={{}} reload={reload} />))
    act(() => tid('profile.nameEdit').click())
    const input = tid('profile.nameInput')
    act(() => {
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(input, 'Janet')
      input.dispatchEvent(new Event('input', { bubbles: true }))
    })
    await act(async () => { tid('profile.nameSave').click() })
    expect(updateProfile).toHaveBeenCalledWith('tok', { display_name: 'Janet' })
    expect(refreshUser).toHaveBeenCalled()
    expect(updateProfile.mock.invocationCallOrder[0]).toBeLessThan(refreshUser.mock.invocationCallOrder[0])
  })

  it('rejects a 3 MB image without a request', async () => {
    act(() => root.render(<ProfileSection account={{}} />))
    const file = new File([new Uint8Array(3 * 1024 * 1024)], 'big.png', { type: 'image/png' })
    const input = tid('profile.avatarFile')
    Object.defineProperty(input, 'files', { value: [file], configurable: true })
    await act(async () => { input.dispatchEvent(new Event('change', { bubbles: true })) })
    expect(uploadAvatar).not.toHaveBeenCalled()
    expect(tid('profile.error').textContent).toContain('2 MB')
  })
})
