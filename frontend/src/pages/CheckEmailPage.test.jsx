// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { MemoryRouter } from 'react-router-dom'

vi.mock('../services/authApi', () => ({ resendVerification: vi.fn() }))
vi.mock('../telemetry/client', () => ({ emit: vi.fn() }))

import CheckEmailPage from './CheckEmailPage'
import { resendVerification } from '../services/authApi'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

let container, root
const tid = (id) => container.querySelector(`[data-tid="${id}"]`)
const render = async (entry) => act(async () => root.render(
  <MemoryRouter initialEntries={[entry]}><CheckEmailPage /></MemoryRouter>,
))

beforeEach(() => {
  vi.useFakeTimers()
  vi.clearAllMocks()
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
})
afterEach(() => { act(() => root.unmount()); container.remove(); vi.useRealTimers() })

describe('CheckEmailPage', () => {
  it('names the address and the 30 minute window', async () => {
    await render({ pathname: '/check-email', state: { email: 'jo@example.com' } })
    expect(tid('check-email-sent').textContent).toBe('We sent a link to jo@example.com. It works for 30 minutes.')
  })

  it('reads the address from ?email= too', async () => {
    await render('/check-email?email=x@y.io')
    expect(tid('check-email-sent').textContent).toContain('x@y.io')
  })

  it('keeps resend disabled for 60 seconds, then resends and restarts the cooldown', async () => {
    resendVerification.mockResolvedValue({ status: 'verification_sent' })
    await render({ pathname: '/check-email', state: { email: 'jo@example.com' } })
    const btn = tid('check-email-resend')
    expect(btn.disabled).toBe(true)
    await act(async () => { vi.advanceTimersByTime(59000) })
    expect(btn.disabled).toBe(true)
    await act(async () => { vi.advanceTimersByTime(1000) })
    expect(btn.disabled).toBe(false)
    await act(async () => btn.click())
    expect(resendVerification).toHaveBeenCalledWith('jo@example.com')
    expect(tid('check-email-resent')).toBeTruthy()
    expect(tid('check-email-resend').disabled).toBe(true)
  })

  it('shows the error when resend fails', async () => {
    resendVerification.mockRejectedValue({ status: 503, code: 'email_unavailable', detail: '' })
    await render({ pathname: '/check-email', state: { email: 'jo@example.com' } })
    await act(async () => { vi.advanceTimersByTime(60000) })
    await act(async () => tid('check-email-resend').click())
    expect(tid('check-email-error').textContent).toMatch(/isn't available/i)
  })
})
