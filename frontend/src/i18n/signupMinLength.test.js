// @vitest-environment node
import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { LANGUAGE_CODES } from './languages'

// The sign-up copy must state the server's minimum (10, /config min_password_length).
const DIGITS = { bn: '১০' }

describe('signup password copy', () => {
  for (const lang of LANGUAGE_CODES) {
    it(`${lang} says 10 characters`, () => {
      const json = JSON.parse(readFileSync(new URL(`./locales/${lang}/signup.json`, import.meta.url), 'utf8'))
      const ten = DIGITS[lang] || '10'
      expect(json.password.placeholder).toContain(ten)
      expect(json.strength.hint.tooShort).toContain(ten)
    })
  }
})
