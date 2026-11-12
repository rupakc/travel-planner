// @vitest-environment node
import { describe, it, expect } from 'vitest'
import { readFileSync, readdirSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { join } from 'node:path'

// tokens.css remaps every palette family (slate, gray, teal, ...) per theme, so
// a `dark:` utility of the same families double-inverts (dark-on-dark text,
// pale cards). Trip pages must rely on the remap alone.
const root = fileURLToPath(new URL('..', import.meta.url))
const files = [
  ...readdirSync(join(root, 'components/trips')).filter((f) => f.endsWith('.jsx') && !f.includes('.test.')).map((f) => join(root, 'components/trips', f)),
  join(root, 'pages/TripsPage.jsx'),
  join(root, 'components/play/CountriesVisited.jsx'),
]
const FAMILIES = 'slate|gray|stone|teal|amber|red|rose|emerald|green|sky|blue|violet|purple|yellow|indigo|orange|cyan|lime|pink|fuchsia|primary|accent'
const BAD = new RegExp(`dark:(?:[a-z-]+:)*[a-z]+-(?:${FAMILIES})-\\d+`, 'g')

describe('dark mode on trip pages', () => {
  it('does not pair dark: palette utilities that tokens.css already remaps', () => {
    const hits = files.flatMap((f) => (readFileSync(f, 'utf8').match(BAD) || []).map((m) => `${f.replace(root, '')}: ${m}`))
    expect(hits).toEqual([])
  })
})
