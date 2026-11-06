// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { MemoryRouter } from 'react-router-dom'

vi.mock('../../context/AuthContext', () => ({
  useAuth: () => ({ user: { username: 'rupak' }, logout: vi.fn(), isAdmin: true }),
}))
vi.mock('../../context/AlertsContext', () => ({ useAlerts: () => ({ unread: 2 }) }))
vi.mock('../alerts/NotificationBell', () => ({ default: () => null }))

import NavBar from './NavBar'

globalThis.IS_REACT_ACT_ENVIRONMENT = true
let container, root

beforeEach(async () => {
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
  await act(async () => root.render(<MemoryRouter initialEntries={['/nearby']}><NavBar /></MemoryRouter>))
})
afterEach(() => { act(() => root.unmount()); container.remove() })

describe('NavBar', () => {
  it('has a Near me tab; desktop tabs keep their names when the labels are icon-only', () => {
    const desktop = [...container.querySelectorAll('.bg-slate-100\\/80 button')]
    expect(desktop.map(b => b.getAttribute('aria-label'))).toEqual(
      ['Search', 'Chat', 'Near me', 'Alerts, 2 unread', 'Preferences', 'Admin'])
    const near = desktop[2]
    expect(near.getAttribute('title')).toBe('Near me')
    expect(near.getAttribute('aria-current')).toBe('page')
    expect(near.getAttribute('data-tour')).toBe('nav-near-me')
    expect(near.className).toContain('whitespace-nowrap')
    expect(near.querySelector('span').className).toContain('hidden lg:inline')
  })

  it('keeps the mobile menu with full labels', async () => {
    await act(async () => container.querySelector('[aria-label="Menu"]').click())
    const drawer = container.querySelector('.sm\\:hidden.flex-col')
    const items = [...drawer.querySelectorAll('button')]
    expect(items.map(b => b.textContent)).toContain('Near me')
    expect(items.every(b => b.getAttribute('aria-label') === null)).toBe(true)
    expect(items[2].querySelector('span').className).toBe('')
  })
})
