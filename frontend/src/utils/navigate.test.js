// @vitest-environment jsdom
import { describe, it, expect } from 'vitest'
import { safeAuthStart } from './navigate'

describe('safeAuthStart', () => {
  it('accepts same-origin /api/auth/ paths with their query', () => {
    expect(safeAuthStart('/api/auth/oauth/github/start?link=t')).toBe('/api/auth/oauth/github/start?link=t')
  })
  it.each(['https://evil.example/api/auth/x', '/other', '/api/auth/../x', '/api/auth/%2e%2e/x', '//evil.com/api/auth/', '/api/auth\\x', null])('rejects %s', (u) => {
    expect(safeAuthStart(u)).toBeNull()
  })
})
