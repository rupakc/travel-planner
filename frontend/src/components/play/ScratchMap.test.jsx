// @vitest-environment jsdom
import { describe, it, expect } from 'vitest'
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import '../../i18n'
import ScratchMap from './ScratchMap'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

describe('ScratchMap', () => {
  it('renders an accessible map with visited countries filled', async () => {
    const el = document.createElement('div')
    document.body.appendChild(el)
    const root = createRoot(el)
    await act(async () => { root.render(<ScratchMap countries={[{ code: 'FR' }, { code: 'JP' }]} />) })
    for (let i = 0; i < 50 && !el.querySelector('svg'); i++) {
      await act(async () => { await new Promise((r) => setTimeout(r, 50)) })
    }
    const svg = el.querySelector('svg[role="img"]')
    expect(svg.getAttribute('aria-label')).toContain('2')
    expect(el.querySelector('[data-tid="play.map.FR"]').getAttribute('class')).toContain('fill-teal-500')
    const de = el.querySelector('[data-tid="play.map.DE"]')
    expect(de.getAttribute('class')).toContain('fill-slate-300')
    await act(async () => { de.dispatchEvent(new MouseEvent('click', { bubbles: true })) })
    expect(el.querySelector('[data-tid="play.scratchmap.label"]').textContent).toContain('Germany')
    const fr = el.querySelector('[data-tid="play.map.FR"]')
    expect(fr.getAttribute('tabindex')).toBe('0')
    expect(fr.getAttribute('aria-label')).toContain('France')
    await act(async () => { fr.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true })) })
    expect(el.querySelector('[data-tid="play.scratchmap.label"]').textContent).toContain('France')
    await act(async () => { de.dispatchEvent(new KeyboardEvent('keydown', { key: ' ', bubbles: true })) })
    expect(el.querySelector('[data-tid="play.scratchmap.label"]').textContent).toContain('Germany')
    act(() => root.unmount())
  })
})
