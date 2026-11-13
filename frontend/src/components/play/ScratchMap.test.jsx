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
    const svg = el.querySelector('svg[role="group"]')
    expect(svg.getAttribute('aria-label')).toContain('2')
    expect(el.querySelector('[data-tid="play.map.FR"]').getAttribute('class')).toContain('fill-teal-500')
    const de = el.querySelector('[data-tid="play.map.DE"]')
    expect(de.getAttribute('class')).toContain('fill-slate-300')
    expect(svg.getAttribute('aria-describedby')).toBe('countries-visited-list')
    // only visited countries are tab stops
    expect(el.querySelectorAll('path[tabindex]').length).toBe(2)
    expect(de.hasAttribute('tabindex')).toBe(false)
    expect(de.hasAttribute('role')).toBe(false)
    await act(async () => { de.dispatchEvent(new MouseEvent('click', { bubbles: true })) })
    expect(el.querySelector('[data-tid="play.scratchmap.label"]').textContent).toContain('Germany')
    const fr = el.querySelector('[data-tid="play.map.FR"]')
    const jp = el.querySelector('[data-tid="play.map.JP"]')
    expect(fr.getAttribute('role')).toBe('button')
    expect(fr.getAttribute('aria-label')).toContain('France')
    expect([fr, jp].map((p) => p.getAttribute('tabindex')).sort()).toEqual(['-1', '0'])
    await act(async () => { fr.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true })) })
    expect(el.querySelector('[data-tid="play.scratchmap.label"]').textContent).toContain('France')
    // arrow keys rove among visited countries
    await act(async () => { fr.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true })) })
    const label = el.querySelector('[data-tid="play.scratchmap.label"]').textContent
    expect(label).toContain('Japan')
    expect(jp.getAttribute('tabindex')).toBe('0')
    expect(fr.getAttribute('tabindex')).toBe('-1')
    act(() => root.unmount())
  })
})
