import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

// Render must be pure (StrictMode, concurrent rendering): the provider's
// body may create refs but never write them — writes belong in effects or
// callbacks. Statements at the component body's indentation (2 spaces) that
// assign to `.current`, or branch on one, are render-time side effects.
describe('AlertsProvider render purity', () => {
  it('writes no refs during render', () => {
    const src = readFileSync(resolve(process.cwd(), 'src/context/AlertsContext.jsx'), 'utf8')
    const body = src.slice(src.indexOf('export function AlertsProvider'), src.indexOf('export function useAlerts'))
    const offenders = body.split('\n').filter(line =>
      /^ {2}[\w.]+\.current\s*=[^=]/.test(line) || /^ {2}if \(.*\.current/.test(line))
    expect(offenders).toEqual([])
  })
})
