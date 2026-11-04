import { describe, it, expect } from 'vitest'
import { safeReturnPath, loginPathFor, returnPathFrom } from './returnPath'

describe('safeReturnPath', () => {
  it.each([
    ['/alerts?watch=1&replan=1', '/alerts?watch=1&replan=1'],
    ['/alerts?watch=1#watch-1', '/alerts?watch=1#watch-1'],
    ['/chat', '/chat'],
    ['/', '/'],
  ])('keeps same-origin path %s', (raw, out) => expect(safeReturnPath(raw)).toBe(out))

  it.each([
    'https://evil.example/alerts', '//evil.example/x', '/\\evil.example', '\\\\evil',
    'javascript:alert(1)', 'alerts', '', null, undefined, 42,
    '/login', '/login?next=/alerts', '/%2F%2Fevil.example', ' /alerts',
  ])('rejects %s', (raw) => expect(safeReturnPath(raw)).toBe('/'))
})

describe('loginPathFor', () => {
  it('carries the intended page in ?next=', () => {
    expect(loginPathFor({ pathname: '/alerts', search: '?watch=1&replan=1', hash: '' }))
      .toBe('/login?next=%2Falerts%3Fwatch%3D1%26replan%3D1')
  })
  it('is plain /login for the home page', () => {
    expect(loginPathFor({ pathname: '/', search: '', hash: '' })).toBe('/login')
  })
})

describe('returnPathFrom', () => {
  it('prefers ?next=, then router state, else home', () => {
    expect(returnPathFrom({ search: '?next=%2Falerts%3Fwatch%3D2' })).toBe('/alerts?watch=2')
    expect(returnPathFrom({ search: '', state: { from: { pathname: '/alerts', search: '?watch=3' } } })).toBe('/alerts?watch=3')
    expect(returnPathFrom({ search: '?next=https%3A%2F%2Fevil.example' })).toBe('/')
    expect(returnPathFrom({ search: '' })).toBe('/')
  })
})
