// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { act } from 'react'
import { createRoot } from 'react-dom/client'

vi.mock('../context/AuthContext', () => ({ useAuth: () => ({ token: 'tok' }) }))
vi.mock('../services/accountApi', () => ({ getAccount: vi.fn() }))
vi.mock('../components/account/ProfileSection', () => ({
  default: ({ account, reload }) => (
    <div>
      <span data-tid="state">{account ? account.id : 'none'}</span>
      <button data-tid="reload" onClick={reload}>r</button>
    </div>
  ),
}))
vi.mock('../components/account/SettingsSection', () => ({ default: () => null }))
vi.mock('../components/account/SecuritySection', () => ({ default: () => null }))
vi.mock('../components/account/QuotaSection', () => ({ default: () => null }))
vi.mock('../components/account/DataSection', () => ({ default: () => null }))
vi.mock('../components/game/GameSection', () => ({ default: () => { throw new Error('boom') } }))

import { initI18n } from '../i18n/index'
import { getAccount } from '../services/accountApi'
import AccountPage from './AccountPage'

globalThis.IS_REACT_ACT_ENVIRONMENT = true
let container, root
beforeEach(async () => {
  await initI18n({ lng: 'en' })
  getAccount.mockReset()
  vi.spyOn(console, 'error').mockImplementation(() => {})
  container = document.createElement('div'); document.body.appendChild(container); root = createRoot(container)
})
afterEach(() => { act(() => root.unmount()); container.remove(); vi.restoreAllMocks() })
const tid = (id) => container.querySelector(`[data-tid="${id}"]`)

describe('AccountPage', () => {
  it('keeps the previous account on a non-404 reload error, clears it on 404', async () => {
    getAccount.mockResolvedValueOnce({ id: 'u1' })
    await act(async () => root.render(<AccountPage />))
    expect(tid('state').textContent).toBe('u1')
    getAccount.mockRejectedValueOnce({ status: 500 })
    await act(async () => { tid('reload').click() })
    expect(tid('state').textContent).toBe('u1')
    getAccount.mockRejectedValueOnce({ status: 404 })
    await act(async () => { tid('reload').click() })
    expect(tid('state').textContent).toBe('none')
  })

  it('shows a notice for a section that throws, without losing the others', async () => {
    getAccount.mockResolvedValue({ id: 'u1' })
    await act(async () => root.render(<AccountPage />))
    expect(tid('account.sectionFailed')).not.toBeNull()
    expect(tid('state')).not.toBeNull()
  })
})
