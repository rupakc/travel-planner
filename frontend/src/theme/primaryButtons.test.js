import { describe, it, expect } from 'vitest'
import fs from 'node:fs'
import path from 'node:path'

function walk(dir, out = []) {
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    const p = path.join(dir, e.name)
    if (e.isDirectory()) walk(p, out)
    else if (p.endsWith('.jsx')) out.push(p)
  }
  return out
}

describe('primary buttons', () => {
  it('no old teal primary together with text-white in one className', () => {
    const root = path.resolve(__dirname, '..')
    const OLD = 'bg-teal-' + '600'
    const bad = []
    for (const f of walk(root)) {
      const src = fs.readFileSync(f, 'utf8')
      for (const m of src.matchAll(/(className|class)=(\{`[^`]*`\}|"[^"]*"|'[^']*'|\{[^}]*\})/g)) {
        if (m[0].includes(OLD) && /\btext-white\b/.test(m[0])) bad.push(path.relative(root, f))
      }
    }
    expect(bad).toEqual([])
  })
})
