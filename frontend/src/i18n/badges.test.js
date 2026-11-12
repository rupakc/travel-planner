// @vitest-environment node
// Every badge in the server's rules.json needs a name and description in every language.
import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { join } from 'node:path'
import { LANGUAGES } from './languages'

const RULES = fileURLToPath(new URL('../../../backend/app/game/rules.json', import.meta.url))
const ids = (() => {
  const b = JSON.parse(readFileSync(RULES, 'utf8')).badges
  return Array.isArray(b) ? b.map((x) => x.id) : Object.keys(b)
})()

describe('badge copy', () => {
  for (const { code } of LANGUAGES) {
    it(`${code} has name and desc for every rules.json badge`, () => {
      const f = fileURLToPath(new URL(`./locales/${code}/game.json`, import.meta.url))
      const badges = JSON.parse(readFileSync(f, 'utf8')).badges
      const missing = ids.filter((id) => !badges[id]?.name || !badges[id]?.desc)
      expect(missing).toEqual([])
    })
  }
})
