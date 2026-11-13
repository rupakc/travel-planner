// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { createRoot } from 'react-dom/client'
import { act } from 'react'

const themeState = vi.hoisted(() => ({ resolved: 'light' }))
const drawn = vi.hoisted(() => [])
vi.mock('../../theme/ThemeContext', () => ({ useTheme: () => ({ resolved: themeState.resolved }) }))
vi.mock('../../utils/savingsCard', async (orig) => ({
  ...(await orig()),
  drawSavingsCard: (ctx, s, lines, theme) => { drawn.push(theme) },
}))

import SavingsShareCard from './SavingsShareCard'

globalThis.IS_REACT_ACT_ENVIRONMENT = true
let container, root

beforeEach(() => {
  drawn.length = 0
  // The OS says dark; the app theme must still win.
  window.matchMedia = () => ({ matches: true, addEventListener() {}, removeEventListener() {} })
  HTMLCanvasElement.prototype.getContext = () => ({})
  container = document.createElement('div'); document.body.appendChild(container); root = createRoot(container)
})
afterEach(async () => { await act(async () => root.unmount()); container.remove() })

describe('SavingsShareCard theme', () => {
  it('draws with the app theme, not the OS colour scheme', async () => {
    themeState.resolved = 'light'
    await act(async () => root.render(<SavingsShareCard savings={{ total_usd: 10, drops_caught: 1 }} onClose={() => {}} />))
    expect(drawn.at(-1)).toBe('light')
    themeState.resolved = 'dark'
    await act(async () => root.render(<SavingsShareCard savings={{ total_usd: 10, drops_caught: 1 }} onClose={() => {}} />))
    expect(drawn.at(-1)).toBe('dark')
  })
})
