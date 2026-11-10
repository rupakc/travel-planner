// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach } from 'vitest'
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import TripMap from '../components/TripMap'
import { pinIcon } from '../components/import/ImportMap'

const OLD_LITERALS = ['#0d9488', '#6366f1', '#f59e0b', '#ef4444', '#8b5cf6', '#6b7280', '#b45309']

globalThis.IS_REACT_ACT_ENVIRONMENT = true

const days = [{
  day_number: 1, city: 'Tokyo',
  slots: [
    { lat: 35.68, lng: 139.76, activity: 'Temple', time_of_day: 'morning' },
    { lat: 35.7, lng: 139.8, activity: 'Market', time_of_day: 'noon', from_link: true },
  ],
}]

describe('dark surfaces', () => {
  beforeEach(() => document.documentElement.classList.add('dark'))
  afterEach(() => document.documentElement.classList.remove('dark'))

  it('TripMap renders no literal hex colours in dark mode', () => {
    const container = document.createElement('div')
    document.body.appendChild(container)
    const root = createRoot(container)
    act(() => { root.render(<TripMap days={days} />) })
    const html = container.innerHTML.toLowerCase()
    expect(html).toContain('leaflet')
    for (const hex of OLD_LITERALS) expect(html).not.toContain(hex)
    // Leaflet's own attribution flag SVG carries hex fills; ours must not.
    const ours = html.replace(/<svg[^>]*leaflet-attribution-flag[\s\S]*?<\/svg>/g, '')
    expect(ours).not.toMatch(/#[0-9a-f]{3,6}\b/)
    // Pin numbers follow the theme (white in light, the dark surface in dark), not a fixed white.
    expect(html).toContain('color:rgb(var(--c-white))')
    expect(html).not.toMatch(/color:\s*white/)
    act(() => root.unmount())
    container.remove()
  })

  it('import pins use the theme variable for the number colour', () => {
    for (const approximate of [false, true]) {
      const html = pinIcon(1, 'sight', approximate, null).options.html
      expect(html).not.toMatch(/color:\s*white|#fff/i)
      if (!approximate) expect(html).toContain('color:rgb(var(--c-white))')
    }
  })

  it('index.css dims map tiles in dark mode only', () => {
    const css = readFileSync(resolve(process.cwd(), 'src/index.css'), 'utf8')
    expect(css).toMatch(/html\.dark\s+\.leaflet-tile-pane\s*\{[^}]*brightness\(\.75\)/)
  })
})
