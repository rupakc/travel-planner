// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { MemoryRouter, Routes, Route, useLocation } from 'react-router-dom'

const auth = { token: 'tok', logout: vi.fn() }
vi.mock('../../context/AuthContext', () => ({ useAuth: () => auth }))
vi.mock('../../services/accountApi', () => ({ exportAccount: vi.fn(), deleteAccount: vi.fn() }))
vi.mock('../../telemetry/client', () => ({ emit: vi.fn() }))

import DataSection from './DataSection'
import { exportAccount, deleteAccount } from '../../services/accountApi'
import { emit } from '../../telemetry/client'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

let container, root, where
function Where() { where = useLocation(); return null }
const account = (hasPassword = true) => ({ user: { username: 'jane', has_password: hasPassword } })
const render = async (acct = account()) => {
  await act(async () => root.render(
    <MemoryRouter initialEntries={['/account']}>
      <Where />
      <Routes>
        <Route path="/account" element={<DataSection account={acct} />} />
        <Route path="*" element={<p>elsewhere</p>} />
      </Routes>
    </MemoryRouter>,
  ))
}
const tid = (id) => container.querySelector(`[data-tid="${id}"]`)
const type = async (el, value) => {
  const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set
  await act(async () => { set.call(el, value); el.dispatchEvent(new Event('input', { bubbles: true })) })
}
const click = (el) => act(async () => { el.dispatchEvent(new MouseEvent('click', { bubbles: true })) })

beforeEach(() => {
  vi.clearAllMocks()
  URL.createObjectURL = vi.fn(() => 'blob:x')
  URL.revokeObjectURL = vi.fn()
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
})
afterEach(() => { act(() => root.unmount()); container.remove() })

describe('DataSection', () => {
  it('the delete dialog traps Tab, closes on Escape and returns focus to Delete', async () => {
    await render()
    await click(tid('account.data.delete'))
    const input = tid('account.data.confirm-input')
    const cancel = tid('account.data.cancel')
    expect(document.activeElement).toBe(input)
    const tab = (shiftKey = false) => act(async () => {
      document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Tab', shiftKey, bubbles: true, cancelable: true }))
    })
    // Confirm is disabled (nothing typed), so Cancel is the last stop: Tab wraps to the input.
    cancel.focus()
    await tab()
    expect(document.activeElement).toBe(input)
    await tab(true)
    expect(document.activeElement).toBe(cancel)
    // Focus that escaped the dialog is pulled back in.
    tid('account.data.export').focus()
    await tab()
    expect(document.activeElement).toBe(input)
    await act(async () => { document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true })) })
    expect(tid('account.data.dialog')).toBeNull()
    expect(document.activeElement).toBe(tid('account.data.delete'))
  })

  it('Cancel also returns focus to Delete', async () => {
    await render()
    await click(tid('account.data.delete'))
    await click(tid('account.data.cancel'))
    expect(tid('account.data.dialog')).toBeNull()
    expect(document.activeElement).toBe(tid('account.data.delete'))
  })

  it('a missing has_password counts as a password account', async () => {
    await render({ user: { username: 'jane' } })
    await click(tid('account.data.delete'))
    expect(tid('account.data.confirm-input').getAttribute('type')).toBe('password')
  })

  it('renders nothing without an account', async () => {
    await render(null)
    expect(container.innerHTML).toBe('')
  })

  it('export creates, downloads and revokes an object URL', async () => {
    exportAccount.mockResolvedValue(new Blob(['{}']))
    const clicked = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
    await render()
    await click(tid('account.data.export'))
    expect(exportAccount).toHaveBeenCalledWith('tok')
    expect(URL.createObjectURL).toHaveBeenCalledTimes(1)
    expect(clicked).toHaveBeenCalledTimes(1)
    expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:x')
    expect(emit).toHaveBeenCalledWith('account_action', { action: 'export' })
    clicked.mockRestore()
  })

  it('shows an error when export fails and creates no URL', async () => {
    exportAccount.mockRejectedValue({ status: 429, code: 'rate_limited', detail: '', extra: {} })
    await render()
    await click(tid('account.data.export'))
    expect(tid('account.data.export-error')).not.toBeNull()
    expect(URL.createObjectURL).not.toHaveBeenCalled()
  })

  it('delete stays disabled until the password is entered', async () => {
    await render()
    await click(tid('account.data.delete'))
    expect(tid('account.data.confirm').disabled).toBe(true)
    await type(tid('account.data.confirm-input'), 'hunter2hunter2')
    expect(tid('account.data.confirm').disabled).toBe(false)
  })

  it('without a password it needs the exact username', async () => {
    await render(account(false))
    await click(tid('account.data.delete'))
    const input = tid('account.data.confirm-input')
    expect(input.type).toBe('text')
    await type(input, 'jan')
    expect(tid('account.data.confirm').disabled).toBe(true)
    await type(input, 'jane')
    expect(tid('account.data.confirm').disabled).toBe(false)
    deleteAccount.mockResolvedValue(null)
    await click(tid('account.data.confirm'))
    expect(deleteAccount).toHaveBeenCalledWith('tok', { confirm_username: 'jane' })
  })

  it('shows 403 password_incorrect inline and stays signed in', async () => {
    deleteAccount.mockRejectedValue({ status: 403, code: 'password_incorrect', detail: 'x', extra: {} })
    await render()
    await click(tid('account.data.delete'))
    await type(tid('account.data.confirm-input'), 'wrongwrongwrong')
    await click(tid('account.data.confirm'))
    expect(deleteAccount).toHaveBeenCalledWith('tok', { password: 'wrongwrongwrong' })
    expect(tid('account.data.delete-error').textContent).toBe('That password is incorrect.')
    expect(auth.logout).not.toHaveBeenCalled()
    expect(tid('account.data.confirm').disabled).toBe(false)
  })

  it('success logs out and goes to /login with the deleted notice state', async () => {
    deleteAccount.mockResolvedValue(null)
    await render()
    await click(tid('account.data.delete'))
    await type(tid('account.data.confirm-input'), 'correct-password')
    await click(tid('account.data.confirm'))
    expect(auth.logout).toHaveBeenCalledTimes(1)
    expect(where.pathname).toBe('/login')
    expect(where.state).toEqual({ notice: 'Your account was deleted.', notice_code: 'account_deleted' })
    expect(emit).toHaveBeenCalledWith('account_action', { action: 'delete' })
  })
})
