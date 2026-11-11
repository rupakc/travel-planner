// @vitest-environment jsdom
import { describe, it, expect, afterEach, vi } from 'vitest'
import { errorSource, startPerf } from './perf'

describe('errorSource', () => {
  it('keeps a script basename + line', () => {
    expect(errorSource('https://voyager.example/assets/index-Ab12.js?v=3', 12)).toBe('index-Ab12.js:12')
    expect(errorSource('/src/App.jsx', 4)).toBe('App.jsx:4')
    expect(errorSource('/m/worker.mjs', 1)).toBe('worker.mjs:1')
    expect(errorSource('/m/util.ts', 9)).toBe('util.ts:9')
  })

  it('is unknown for anything that is not a script file', () => {
    expect(errorSource('https://x/share/abc123', 5)).toBe('unknown')
    expect(errorSource('https://x/', 5)).toBe('unknown')
    expect(errorSource('', 5)).toBe('unknown')
    expect(errorSource(undefined, 5)).toBe('unknown')
  })
})

describe('error capture', () => {
  let perf
  afterEach(() => perf?.stop())

  it('reports kind + source only, never the message or the page path', () => {
    const emit = vi.fn()
    perf = startPerf(emit)
    window.dispatchEvent(new ErrorEvent('error', { message: 'jane@x.com broke', filename: 'https://x/share/abc123', lineno: 3 }))
    window.dispatchEvent(new ErrorEvent('error', { message: 'boom', filename: 'https://x/assets/index-9.js', lineno: 7 }))
    const errors = emit.mock.calls.filter(([e]) => e === 'error')
    expect(errors).toEqual([
      ['error', { kind: 'js', source: 'unknown' }],
      ['error', { kind: 'js', source: 'index-9.js:7' }],
    ])
    expect(JSON.stringify(emit.mock.calls)).not.toMatch(/jane|boom|abc123/)
  })
})
