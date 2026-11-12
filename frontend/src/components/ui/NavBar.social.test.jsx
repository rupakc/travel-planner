// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { MemoryRouter } from 'react-router-dom'

vi.mock('../../context/AuthContext', () => ({
  useAuth: () => ({ user: { username: 'rupak' }, logout: vi.fn(), isAdmin: false }),
}))
vi.mock('../../context/AlertsContext', () => ({ useAlerts: () => ({ unread: 0 }) }))
vi.mock('../alerts/NotificationBell', () => ({ default: () => null }))
vi.mock('../../telemetry/client', () => ({ emit: vi.fn() }))
vi.mock('../../hooks/useJourney', () => ({ useJourney: () => ({ enabled: false, loaded: true }) }))
vi.mock('../../hooks/useHasTrips', () => ({ useHasTrips: () => ({ hasTrips: false, loading: false }) }))
const social = vi.hoisted(() => ({ value: { enabled: false, loaded: true } }))
vi.mock('../../hooks/useSocial', () => ({ useSocialEnabled: () => social.value }))

import { initI18n } from '../../i18n/index'
import { ThemeProvider } from '../../theme/ThemeContext'
import NavBar from './NavBar'

globalThis.IS_REACT_ACT_ENVIRONMENT = true
let container, root
const mount = async (path = '/chat') => {
  await act(async () => root.render(
    <ThemeProvider><MemoryRouter initialEntries={[path]}><NavBar /></MemoryRouter></ThemeProvider>))
}
beforeEach(async () => {
  await initI18n({ lng: 'en' })
  container = document.createElement('div'); document.body.appendChild(container); root = createRoot(container)
})
afterEach(() => { act(() => root.unmount()); container.remove() })

describe('NavBar Ideas entry', () => {
  it('is hidden without features.social', async () => {
    social.value = { enabled: false, loaded: true }
    await mount()
    expect(container.querySelector('[data-tid="nav.feed"]')).toBeNull()
  })

  it('is shown with features.social and marked current on /feed and profiles', async () => {
    social.value = { enabled: true, loaded: true }
    await mount('/u/ann')
    const tab = container.querySelector('[data-tid="nav.feed"]')
    expect(tab).not.toBeNull()
    expect(tab.getAttribute('aria-current')).toBe('page')
    expect(tab.textContent).toContain('Ideas')
  })
})
