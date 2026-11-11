// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { act } from 'react'
import { createRoot } from 'react-dom/client'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

const api = vi.hoisted(() => ({ getSettings: vi.fn(), patchSettings: vi.fn() }))
vi.mock('../../services/accountApi', () => api)
const auth = vi.hoisted(() => ({ value: { token: 'tok' } }))
vi.mock('../../context/AuthContext', () => ({ useOptionalAuth: () => auth.value }))

import { ThemeProvider, useTheme } from '../../theme/ThemeContext'
import i18n, { initI18n, setLanguage } from '../../i18n'
import SettingsSync, { useAccountSettings, resetAccountSettings, DEFAULT_SETTINGS } from './SettingsSync'

const SERVER = { ...DEFAULT_SETTINGS }
let themeApi, settingsApi

function Probe() {
  themeApi = useTheme()
  settingsApi = useAccountSettings()
  return null
}

describe('SettingsSync', () => {
  let container, root

  async function mount() {
    await act(async () => {
      root.render(<ThemeProvider><SettingsSync /><Probe /></ThemeProvider>)
    })
    await act(async () => {})
  }

  beforeEach(async () => {
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] })
    window.matchMedia = vi.fn(() => ({ matches: false, addEventListener() {}, removeEventListener() {} }))
    localStorage.clear()
    await initI18n({ lng: 'en' })
    await i18n.changeLanguage('en')
    api.getSettings.mockReset().mockResolvedValue({ ...SERVER })
    api.patchSettings.mockReset().mockResolvedValue({})
    auth.value = { token: 'tok' }
    resetAccountSettings()
    container = document.createElement('div')
    document.body.appendChild(container)
    root = createRoot(container)
  })

  afterEach(() => {
    act(() => root.unmount())
    container.remove()
    vi.useRealTimers()
  })

  it('applies a server theme at sign-in without patching it back', async () => {
    api.getSettings.mockResolvedValue({ ...SERVER, theme: 'dark' })
    await mount()
    expect(themeApi.theme).toBe('dark')
    expect(document.documentElement.classList.contains('dark')).toBe(true)
    await act(async () => { vi.advanceTimersByTime(2000) })
    expect(api.patchSettings).not.toHaveBeenCalled()
  })

  it('applies a server language', async () => {
    api.getSettings.mockResolvedValue({ ...SERVER, language: 'de' })
    await mount()
    await act(async () => {})
    for (let i = 0; i < 20 && i18n.resolvedLanguage !== 'de'; i += 1) {
      await act(async () => { await new Promise((r) => setImmediate(r)) })
    }
    expect(i18n.resolvedLanguage).toBe('de')
    await act(async () => { vi.advanceTimersByTime(2000) })
    expect(api.patchSettings).not.toHaveBeenCalled()
  })

  it('patches the device choice up when the server holds none', async () => {
    localStorage.setItem('tp_theme', 'dark')
    await mount()
    await act(async () => { vi.advanceTimersByTime(1100) })
    expect(api.patchSettings).toHaveBeenCalledTimes(1)
    expect(api.patchSettings).toHaveBeenCalledWith('tok', { theme: 'dark' })
  })

  it('patches a language change once after the debounce', async () => {
    await mount()
    await act(async () => { await setLanguage('fr'); await setLanguage('es') })
    expect(api.patchSettings).not.toHaveBeenCalled()
    await act(async () => { vi.advanceTimersByTime(1100) })
    expect(api.patchSettings).toHaveBeenCalledTimes(1)
    expect(api.patchSettings).toHaveBeenCalledWith('tok', { language: 'es' })
  })

  it('patches a theme change', async () => {
    await mount()
    await act(async () => { themeApi.setTheme('dark') })
    await act(async () => { vi.advanceTimersByTime(1100) })
    expect(api.patchSettings).toHaveBeenCalledWith('tok', { theme: 'dark' })
  })

  it('goes inactive on a 404', async () => {
    api.getSettings.mockRejectedValue({ status: 404 })
    await mount()
    await act(async () => { await setLanguage('fr') })
    await act(async () => { vi.advanceTimersByTime(2000) })
    expect(api.patchSettings).not.toHaveBeenCalled()
  })

  it('stops after a 404 on patch', async () => {
    api.patchSettings.mockRejectedValue({ status: 404 })
    await mount()
    await act(async () => { await setLanguage('fr') })
    await act(async () => { vi.advanceTimersByTime(1100) })
    await act(async () => { await setLanguage('es') })
    await act(async () => { vi.advanceTimersByTime(1100) })
    expect(api.patchSettings).toHaveBeenCalledTimes(1)
  })

  it('does nothing when signed out', async () => {
    auth.value = { token: null }
    await mount()
    expect(api.getSettings).not.toHaveBeenCalled()
  })

  it('update() changes the shared settings', async () => {
    await mount()
    await act(async () => { settingsApi.update({ hide_game: true }) })
    expect(settingsApi.settings.hide_game).toBe(true)
    await act(async () => { vi.advanceTimersByTime(1100) })
    expect(api.patchSettings).toHaveBeenCalledWith('tok', { hide_game: true })
  })
})
