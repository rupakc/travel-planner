import { describe, it, expect } from 'vitest'
// @vitest-environment node
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import tokens from '../../design/tokens.json'
import { buildCss, FAMILIES, STOPS } from '../../scripts/build-tokens.mjs'
import tailwindConfig from '../../tailwind.config.js'

// Read from disk: vitest stubs CSS imports (even ?raw) to an empty string.
const tokensCss = readFileSync(fileURLToPath(new URL('./tokens.css', import.meta.url)), 'utf8')

// WCAG 2.x relative luminance / contrast ratio.
function luminance(hex) {
  const n = parseInt(hex.replace('#', ''), 16)
  const [r, g, b] = [(n >> 16) & 255, (n >> 8) & 255, n & 255].map((v) => {
    const c = v / 255
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4
  })
  return 0.2126 * r + 0.7152 * g + 0.0722 * b
}
function contrast(a, b) {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x)
  return (hi + 0.05) / (lo + 0.05)
}
const color = (mode, family, stop) => (stop === undefined ? tokens[mode][family] : tokens[mode][family][stop])

const EXPECTED_FAMILIES = [
  'gray', 'slate', 'stone', 'teal', 'amber', 'sky', 'red', 'emerald', 'green', 'violet', 'rose', 'cyan',
  'blue', 'purple', 'yellow', 'indigo', 'pink', 'orange', 'lime', 'fuchsia', 'primary', 'accent',
]

describe('design tokens', () => {
  it('the committed tokens.css is exactly what the generator writes', () => {
    expect(buildCss(tokens)).toBe(tokensCss)
  })

  it('covers exactly the colour families the app uses, plus white', () => {
    expect(FAMILIES).toEqual(EXPECTED_FAMILIES)
    for (const mode of ['palette', 'dark']) {
      expect(Object.keys(tokens[mode]).sort()).toEqual([...EXPECTED_FAMILIES, 'white'].sort())
      expect(tokens[mode].white).toMatch(/^#[0-9a-f]{6}$/)
      expect(tokens[mode].black).toBeUndefined() // overlays stay black
    }
  })

  it('every family has 11 hex stops in both modes', () => {
    expect(STOPS).toEqual(['50', '100', '200', '300', '400', '500', '600', '700', '800', '900', '950'])
    for (const mode of ['palette', 'dark']) {
      for (const family of EXPECTED_FAMILIES) {
        expect(Object.keys(tokens[mode][family])).toEqual(STOPS)
        for (const stop of STOPS) expect(color(mode, family, stop)).toMatch(/^#[0-9a-f]{6}$/)
      }
    }
  })

  it('light values are the Tailwind 3.4 defaults, so light mode looks unchanged', () => {
    const p = tokens.palette
    expect(p.white).toBe('#ffffff')
    expect(p.gray['50']).toBe('#f9fafb')
    expect(p.gray['900']).toBe('#111827')
    expect(p.slate['100']).toBe('#f1f5f9')
    expect(p.teal['600']).toBe('#0d9488')
    expect(p.amber['500']).toBe('#f59e0b')
    expect(p.fuchsia['950']).toBe('#4a044e')
    // primary keeps the teal ramp it had in tailwind.config.js
    expect(p.primary).toEqual(p.teal)
  })

  it('dark neutrals run from a deep night page to near-white text', () => {
    const d = tokens.dark
    for (const fam of ['gray', 'slate', 'stone']) {
      const lums = STOPS.map((s) => luminance(d[fam][s]))
      for (let i = 1; i < lums.length; i++) expect(lums[i]).toBeGreaterThan(lums[i - 1])
    }
    // page (gray-50) < raised card (white) < subtle fill (gray-100)
    expect(luminance(d.gray['50'])).toBeLessThan(luminance(d.white))
    expect(luminance(d.white)).toBeLessThan(luminance(d.gray['100']))
  })

  it('gray-900 on gray-50 reads at WCAG AA in both modes', () => {
    for (const mode of ['palette', 'dark']) {
      expect(contrast(color(mode, 'gray', '900'), color(mode, 'gray', '50'))).toBeGreaterThanOrEqual(4.5)
    }
  })

  it('white text on teal-600 reads at WCAG AA in dark mode', () => {
    expect(contrast(color('dark', 'white'), color('dark', 'teal', '600'))).toBeGreaterThanOrEqual(4.5)
    expect(contrast(color('dark', 'white'), color('dark', 'primary', '600'))).toBeGreaterThanOrEqual(4.5)
  })

  it('white text on teal-600 in light mode is the unchanged Tailwind pair (AA for large text/UI only)', () => {
    // Tailwind's #0d9488 with white is 3.74:1. Light mode must stay identical to
    // today, so this pair cannot reach 4.5 without changing the look (see task-4 report).
    expect(contrast(color('palette', 'white'), color('palette', 'teal', '600'))).toBeGreaterThanOrEqual(3)
  })

  it('muted text (gray-500) stays readable on cards in dark mode', () => {
    expect(contrast(color('dark', 'gray', '500'), color('dark', 'white'))).toBeGreaterThanOrEqual(4.5)
  })

  it('tinted text keeps AA on its own tinted chip in dark mode (e.g. text-amber-700 on bg-amber-50)', () => {
    for (const fam of EXPECTED_FAMILIES) {
      expect(contrast(color('dark', fam, '700'), color('dark', fam, '50'))).toBeGreaterThanOrEqual(4.5)
    }
  })

  it('writes space-separated RGB channels for :root and html.dark', () => {
    expect(tokensCss).toContain(':root {')
    expect(tokensCss).toContain('html.dark {')
    expect(tokensCss).toContain('--c-gray-50: 249 250 251;')
    expect(tokensCss).toContain('--c-white: 255 255 255;')
    expect(tokensCss).not.toContain('--c-black')
  })
})

describe('tailwind config', () => {
  it('uses class-based dark mode', () => {
    expect(tailwindConfig.darkMode).toBe('class')
  })

  it('maps every family to alpha-aware CSS variables', () => {
    const colors = tailwindConfig.theme.extend.colors
    for (const fam of EXPECTED_FAMILIES) {
      for (const stop of STOPS) {
        expect(colors[fam][stop]).toBe(`rgb(var(--c-${fam}-${stop}) / <alpha-value>)`)
      }
    }
    expect(colors.white).toBe('rgb(var(--c-white) / <alpha-value>)')
    expect(colors.black).toBeUndefined()
  })
})
