import { describe, it, expect } from 'vitest'

// The palette tokens (src/theme/tokens.css) already swap under html.dark, so a
// `dark:` colour utility would double-invert (dark text on a dark card).
const sources = import.meta.glob('./*.jsx', { query: '?raw', import: 'default', eager: true })

describe('alerts2 components', () => {
  it('use no dark: utilities (tokens theme themselves)', () => {
    const bad = Object.entries(sources)
      .filter(([name]) => !name.endsWith('.test.jsx'))
      .filter(([, src]) => /(^|[\s"'`])dark:/.test(src))
      .map(([name]) => name)
    expect(bad).toEqual([])
  })
})
