import { describe, it, expect } from 'vitest'
import { wrapCanvasText } from './wrapCanvasText'

const measure = (s) => [...s].length * 10

describe('wrapCanvasText', () => {
  it('splits an unbroken Chinese string into lines that fit', () => {
    const text = '行'.repeat(60)
    const lines = wrapCanvasText(text, 100, measure)
    expect(lines).toHaveLength(6)
    for (const l of lines) expect([...l].length).toBeLessThanOrEqual(10)
    expect(lines.join('')).toBe(text)
  })

  it('wraps English on spaces', () => {
    const lines = wrapCanvasText('aaaa bbbb cccc dddd', 90, measure)
    expect(lines).toEqual(['aaaa bbbb', 'cccc dddd'])
  })

  it('keeps short text on one line and empty text as one empty line', () => {
    expect(wrapCanvasText('hi there', 500, measure)).toEqual(['hi there'])
    expect(wrapCanvasText('', 500, measure)).toEqual([''])
  })
})
