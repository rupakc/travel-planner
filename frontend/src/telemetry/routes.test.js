// @vitest-environment node
import { describe, it, expect } from 'vitest'
import { routeTemplate } from './routes'

describe('routeTemplate (journey routes)', () => {
  it('maps trip paths to templates, never the id', () => {
    expect(routeTemplate('/trips/12/today')).toBe('/trips/:id/:tab')
    expect(routeTemplate('/trips/12')).toBe('/trips/:id')
    expect(routeTemplate('/trips/12/')).toBe('/trips/:id')
  })
  it('knows the static journey routes', () => {
    for (const p of ['/trips', '/explore', '/play', '/you', '/onboarding']) expect(routeTemplate(p)).toBe(p)
  })
  it('keeps the existing routes', () => {
    expect(routeTemplate('/')).toBe('/')
    expect(routeTemplate('/share/abc')).toBe('/share/:token')
    expect(routeTemplate('/nope/1')).toBe('/other')
  })
})
