// @vitest-environment node
// Catalogue rules every namespace in every language must pass. Namespaces are
// discovered from the `en` folder, so a namespace added later is covered
// without touching this file.
import { describe, it, expect } from 'vitest'
import { readdirSync, readFileSync, existsSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { join } from 'node:path'
import { LANGUAGES } from './languages'

const LOCALES = fileURLToPath(new URL('./locales', import.meta.url))
const PLURAL_SUFFIX = /_(zero|one|two|few|many|other)$/
const CODES = LANGUAGES.map((l) => l.code)
const namespaces = readdirSync(join(LOCALES, 'en'))
  .filter((f) => f.endsWith('.json'))
  .map((f) => f.slice(0, -5))
  .sort()

function load(lang, ns) {
  const raw = readFileSync(join(LOCALES, lang, `${ns}.json`), 'utf8')
  return JSON.parse(raw)
}

// { 'nav.search': 'Search', ... } — leaves only; non-string leaves are kept so
// the "every value is a non-empty string" rule can flag them.
function flatten(obj, prefix = '', out = {}) {
  for (const [k, v] of Object.entries(obj)) {
    const key = prefix ? `${prefix}.${k}` : k
    if (v && typeof v === 'object' && !Array.isArray(v)) flatten(v, key, out)
    else out[key] = v
  }
  return out
}

const placeholders = (s) => [...String(s).matchAll(/\{\{\s*([\w.]+)[^}]*\}\}/g)].map((m) => m[1]).sort()
const tags = (s) => [...String(s).matchAll(/<\/?([\w-]+)\s*\/?>/g)].map((m) => m[0]).sort()

// Splits a flat catalogue into plain keys and plural groups. A key counts as a
// plural form only when `en` has `<base>_other`.
function split(flat, enFlat) {
  const plain = {}
  const plural = {}
  for (const [key, value] of Object.entries(flat)) {
    const m = key.match(PLURAL_SUFFIX)
    if (m && `${key.slice(0, -m[0].length)}_other` in enFlat) {
      const base = key.slice(0, -m[0].length)
      ;(plural[base] ||= {})[m[1]] = value
    } else {
      plain[key] = value
    }
  }
  return { plain, plural }
}

describe('catalogue', () => {
  it('has at least the common namespace and a folder per language', () => {
    expect(namespaces).toContain('common')
    for (const code of CODES) expect(existsSync(join(LOCALES, code))).toBe(true)
  })

  it('has no namespace outside en', () => {
    for (const code of CODES) {
      const files = readdirSync(join(LOCALES, code)).filter((f) => f.endsWith('.json'))
      for (const f of files) expect(namespaces, `${code}/${f}`).toContain(f.slice(0, -5))
    }
  })

  for (const ns of namespaces) {
    const enFlat = flatten(load('en', ns))
    const en = split(enFlat, enFlat)

    for (const lang of CODES) {
      describe(`${lang}/${ns}`, () => {
        it('is valid JSON', () => {
          expect(() => load(lang, ns)).not.toThrow()
        })

        // Invalid JSON fails the test above, not the whole collection.
        let parsed = {}
        try { parsed = load(lang, ns) } catch { /* reported by 'is valid JSON' */ }
        const flat = flatten(parsed)
        const cat = split(flat, enFlat)
        const categories = new Intl.PluralRules(lang).resolvedOptions().pluralCategories

        it('has exactly the en keys (plural-aware)', () => {
          expect(Object.keys(cat.plain).sort()).toEqual(Object.keys(en.plain).sort())
          expect(Object.keys(cat.plural).sort()).toEqual(Object.keys(en.plural).sort())
          for (const base of Object.keys(cat.plural)) {
            expect(Object.keys(cat.plural[base]).sort(), `${base} plural forms`).toEqual([...categories].sort())
          }
        })

        it('has no empty or non-string values', () => {
          for (const [key, value] of Object.entries(flat)) {
            expect(typeof value, key).toBe('string')
            expect(value.trim(), key).not.toBe('')
          }
        })

        it('has no value equal to its key', () => {
          for (const [key, value] of Object.entries(flat)) {
            expect(value, key).not.toBe(key)
            expect(value, key).not.toBe(`${ns}:${key}`)
          }
        })

        it('keeps the en {{placeholders}} and <tags>', () => {
          for (const [key, value] of Object.entries(cat.plain)) {
            expect(placeholders(value), key).toEqual(placeholders(en.plain[key]))
            expect(tags(value), key).toEqual(tags(en.plain[key]))
          }
          // A plural form may drop {{count}} ("one hour"), nothing else.
          for (const [base, forms] of Object.entries(cat.plural)) {
            const want = placeholders(en.plural[base].other).filter((p) => p !== 'count')
            for (const [form, value] of Object.entries(forms)) {
              expect(placeholders(value).filter((p) => p !== 'count'), `${base}_${form}`).toEqual(want)
              expect(tags(value), `${base}_${form}`).toEqual(tags(en.plural[base].other))
            }
          }
        })
      })
    }
  }
})
