// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { act } from 'react'
import { createRoot } from 'react-dom/client'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

vi.mock('../../services/accountApi', () => ({ getSettings: vi.fn(), patchSettings: vi.fn() }))
vi.mock('../ConsentPrompt', () => ({ PrivacySwitch: () => <div data-tid="privacy.switch" /> }))

import { ThemeProvider } from '../../theme/ThemeContext'
import { initI18n } from '../../i18n'
import SettingsSection from './SettingsSection'
import { resetAccountSettings, useAccountSettings } from './SettingsSync'

let seen
function Probe() { seen = useAccountSettings().settings; return null }

describe('SettingsSection', () => {
  let container, root
  beforeEach(async () => {
    window.matchMedia = vi.fn(() => ({ matches: false, addEventListener() {}, removeEventListener() {} }))
    await initI18n({ lng: 'en' })
    resetAccountSettings()
    container = document.createElement('div')
    document.body.appendChild(container)
    root = createRoot(container)
  })
  afterEach(() => { act(() => root.unmount()); container.remove() })

  const render = (account) => act(async () => {
    root.render(<ThemeProvider><SettingsSection account={account} /><Probe /></ThemeProvider>)
  })

  it('renders nothing without an account', async () => {
    await render(null)
    expect(container.querySelector('[data-tid="settings.section"]')).toBeNull()
  })

  it('toggling hide_game updates the shared settings', async () => {
    await render({ user: {} })
    const sw = container.querySelector('[data-tid="settings.hide_game"]')
    expect(sw.getAttribute('aria-checked')).toBe('false')
    await act(async () => { sw.click() })
    expect(seen.hide_game).toBe(true)
    expect(sw.getAttribute('aria-checked')).toBe('true')
  })

  it('changes units and shows the telemetry switch', async () => {
    await render({ user: {} })
    expect(container.querySelector('[data-tid="privacy.switch"]')).not.toBeNull()
    const sel = container.querySelector('[data-tid="settings.units"]')
    const setter = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'value').set
    await act(async () => { setter.call(sel, 'imperial'); sel.dispatchEvent(new Event('change', { bubbles: true })) })
    expect(seen.units).toBe('imperial')
  })
})
