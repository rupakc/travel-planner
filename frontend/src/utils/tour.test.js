// @vitest-environment node
import { describe, it, expect } from 'vitest'
import { placeTooltip, tourDoneKey, isTourDone, markTourDone } from './tour'

const viewport = { width: 1200, height: 800 }
const size = { width: 320, height: 180 }
const rect = (left, top, width, height) => ({ left, top, width, height, right: left + width, bottom: top + height })

describe('placeTooltip', () => {
  it('centres the card when there is no target', () => {
    expect(placeTooltip(null, size, viewport)).toEqual({ placement: 'center', top: 310, left: 440 })
  })

  it('puts the card below the target, aligned to its left edge', () => {
    expect(placeTooltip(rect(100, 100, 400, 50), size, viewport)).toEqual({ placement: 'bottom', top: 162, left: 100 })
  })

  it('flips above when there is no room below', () => {
    expect(placeTooltip(rect(100, 600, 400, 50), size, viewport)).toEqual({ placement: 'top', top: 408, left: 100 })
  })

  it('keeps the card inside a 16px gutter horizontally', () => {
    expect(placeTooltip(rect(1100, 100, 80, 40), size, viewport).left).toBe(1200 - 16 - 320)
    expect(placeTooltip(rect(-50, 100, 80, 40), size, viewport).left).toBe(16)
  })

  it('overlays the target bottom when it fills the screen (fits neither above nor below)', () => {
    const tall = placeTooltip(rect(100, 20, 400, 760), size, viewport)
    expect(tall.placement).toBe('inside')
    expect(tall.top).toBe(800 - 16 - 180)
  })

  it('never pushes the card above the screen on a very short viewport', () => {
    const short = { width: 640, height: 300 }
    const p = placeTooltip(rect(100, 20, 400, 260), { width: 320, height: 290 }, short)
    expect(p.top).toBe(16)
  })

  it('fits a narrow phone screen', () => {
    const phone = { width: 375, height: 700 }
    const p = placeTooltip(rect(16, 100, 343, 60), { width: 343, height: 200 }, phone)
    expect(p.left).toBe(16)
    expect(p.left + 343).toBeLessThanOrEqual(375 - 16)
  })
})

describe('tour completion storage', () => {
  const memoryStorage = () => {
    const data = {}
    return { getItem: (k) => (k in data ? data[k] : null), setItem: (k, v) => { data[k] = String(v) } }
  }

  it('is remembered per user', () => {
    const storage = memoryStorage()
    expect(isTourDone('rupak', storage)).toBe(false)
    markTourDone('rupak', storage)
    expect(isTourDone('rupak', storage)).toBe(true)
    expect(isTourDone('someone-else', storage)).toBe(false)
    expect(tourDoneKey('rupak')).toBe('tp_tour_done:rupak')
  })

  it('treats blocked storage as "not done" and never throws', () => {
    const blocked = { getItem: () => { throw new Error('blocked') }, setItem: () => { throw new Error('blocked') } }
    expect(isTourDone('rupak', blocked)).toBe(false)
    expect(() => markTourDone('rupak', blocked)).not.toThrow()
  })
})
