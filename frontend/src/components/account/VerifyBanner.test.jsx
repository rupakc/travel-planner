// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { act } from 'react'
import { createRoot } from 'react-dom/client'

let auth
vi.mock('../../context/AuthContext', () => ({ useAuth: () => auth }))
vi.mock('../../services/accountApi', () => ({ requestEmailVerification: vi.fn() }))
vi.mock('../../telemetry/client', () => ({ emit: vi.fn() }))

import VerifyBanner from './VerifyBanner'
import { requestEmailVerification } from '../../services/accountApi'
import { emit } from '../../telemetry/client'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

let container, root
const tid = (id) => container.querySelector(`[data-tid="${id}"]`)
const render = async () => act(async () => { root.render(<VerifyBanner />) })

beforeEach(() => {
  vi.clearAllMocks()
  sessionStorage.clear()
  auth = { token: 'tok', user: { username: 'a' }, accountVerified: false }
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
})
afterEach(() => { act(() => root.unmount()); container.remove() })

describe('VerifyBanner', () => {
  it('is hidden for verified users', async () => {
    auth.accountVerified = true
    await render()
    expect(container.innerHTML).toBe('')
    expect(emit).not.toHaveBeenCalled()
  })

  it('is hidden on an old backend (no account_verified field)', async () => {
    // AuthContext maps a missing field to accountVerified === true.
    auth = { token: 'tok', user: { username: 'a' }, accountVerified: true }
    await render()
    expect(tid('verify-banner')).toBeNull()
  })

  it('shows for unverified users and emits quota_block once per session', async () => {
    await render()
    expect(tid('verify-banner.text').textContent).toBe('Confirm your email to use the AI planner')
    await act(async () => root.unmount())
    root = createRoot(container)
    await render()
    expect(emit).toHaveBeenCalledTimes(1)
    expect(emit).toHaveBeenCalledWith('quota_block', { bucket: 'search', reason: 'unverified' })
  })

  it('Send link calls the API once', async () => {
    requestEmailVerification.mockResolvedValue({ status: 'verification_sent' })
    await render()
    await act(async () => { tid('verify-banner.send').click() })
    expect(requestEmailVerification).toHaveBeenCalledTimes(1)
    expect(requestEmailVerification).toHaveBeenCalledWith('tok')
    expect(tid('verify-banner.text').textContent).toBe('Link sent. Check your inbox.')
    expect(tid('verify-banner.send')).toBeNull()
  })

  it('dismiss hides it for the session', async () => {
    await render()
    await act(async () => { tid('verify-banner.dismiss').click() })
    expect(tid('verify-banner')).toBeNull()
  })
})
