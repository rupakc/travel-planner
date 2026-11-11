// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { MemoryRouter } from 'react-router-dom'

const logout = vi.fn()
vi.mock('../../context/AuthContext', () => ({
  useAuth: () => ({ logout, user: { username: 'jane', display_name: 'Jane', avatar_url: null } }),
}))

import { initI18n } from '../../i18n/index'
import AccountMenu from './AccountMenu'

globalThis.IS_REACT_ACT_ENVIRONMENT = true
let container, root
beforeEach(async () => {
  await initI18n({ lng: 'en' })
  container = document.createElement('div'); document.body.appendChild(container); root = createRoot(container)
  act(() => root.render(<MemoryRouter><AccountMenu /></MemoryRouter>))
})
afterEach(() => { act(() => root.unmount()); container.remove() })
const tid = (id) => container.querySelector(`[data-tid="${id}"]`)

describe('AccountMenu', () => {
  it('opens with Account, Preferences and Sign out', () => {
    expect(container.querySelector('[role="menu"]')).toBeNull()
    act(() => tid('account.menu').click())
    expect(tid('account.menu.account').textContent).toBe('Account')
    expect(tid('account.menu.preferences').textContent).toBe('Preferences')
    act(() => tid('account.menu.signOut').click())
    expect(logout).toHaveBeenCalled()
    expect(container.querySelector('[role="menu"]')).toBeNull()
  })
})
