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
vi.mock('../../telemetry/client', () => ({ emit: vi.fn() }))

import i18n from 'i18next'
import { emit } from '../../telemetry/client'
import { ThemeProvider } from '../../theme/ThemeContext'
import NavBar from './NavBar'

globalThis.IS_REACT_ACT_ENVIRONMENT = true
let container, root

beforeEach(async () => {
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
  await act(async () => root.render(
    <ThemeProvider><MemoryRouter initialEntries={['/nearby']}><NavBar /></MemoryRouter></ThemeProvider>))
})
afterEach(async () => {
  act(() => root.unmount()); container.remove()
  await act(async () => { await i18n.changeLanguage('en') })
  try { localStorage.clear() } catch { /* ignore */ }
  document.documentElement.classList.remove('dark')
  emit.mockClear()
})

const desktopLabels = () => [...container.querySelectorAll('.bg-slate-100\\/80 button')].map(b => b.getAttribute('aria-label'))

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

  it('offers every language by its native name and switches the labels', async () => {
    const picker = container.querySelector('select[data-tid="nav.language"]')
    const options = [...picker.options].map(o => [o.value, o.textContent])
    expect(options).toEqual([
      ['en', 'English'], ['es', 'Español'], ['de', 'Deutsch'], ['fr', 'Français'],
      ['hi', 'हिन्दी'], ['zh', '中文（简体）'], ['bn', 'বাংলা']])
    expect(picker.value).toBe('en')

    await act(async () => {
      picker.value = 'de'
      picker.dispatchEvent(new Event('change', { bubbles: true }))
    })
    await vi.waitFor(() => expect(desktopLabels()[0]).toBe('Suche'))
    expect(desktopLabels()).toEqual(
      ['Suche', 'Chat', 'In der Nähe', 'Preisalarme, 2 ungelesen', 'Einstellungen', 'Admin'])
    expect(picker.value).toBe('de')
    expect(document.documentElement.lang).toBe('de')
    expect(localStorage.getItem('tp_lang')).toBe('de')
    await vi.waitFor(() => expect(emit).toHaveBeenCalledWith('language_change', { lang: 'de' }))
    // Tour anchors stay stable across languages.
    expect(container.querySelector('[data-tour="nav-near-me"]')).not.toBeNull()
  })

  it('cycles the theme light (default) → dark → system and reports each change', async () => {
    const toggle = container.querySelector('button[data-tid="nav.theme"]')
    const mode = () => toggle.getAttribute('aria-label')
    expect(mode()).toBe('Theme: Light')
    await act(async () => toggle.click())
    expect(mode()).toBe('Theme: Dark')
    expect(document.documentElement.classList.contains('dark')).toBe(true)
    expect(localStorage.getItem('tp_theme')).toBe('dark')
    await vi.waitFor(() => expect(emit).toHaveBeenLastCalledWith('theme_change', { theme: 'dark' }))
    await act(async () => toggle.click())
    expect(mode()).toBe('Theme: System')
    await vi.waitFor(() => expect(emit).toHaveBeenLastCalledWith('theme_change', { theme: 'system' }))
    await act(async () => toggle.click())
    expect(mode()).toBe('Theme: Light')
    expect(document.documentElement.classList.contains('dark')).toBe(false)
  })

  it('tags interactive elements for telemetry', () => {
    const tids = [...container.querySelectorAll('[data-tid]')].map(e => e.getAttribute('data-tid'))
    expect(tids).toEqual(expect.arrayContaining([
      'nav.search', 'nav.chat', 'nav.nearby', 'nav.alerts', 'nav.preferences', 'nav.admin',
      'nav.menu', 'nav.language', 'nav.theme', 'nav.signOut']))
  })
})
