// @vitest-environment node
import { describe, it, expect } from 'vitest'
import { matchSocialPath, profilePath, feedPath } from './paths'

describe('matchSocialPath', () => {
  it('matches the feed, one idea and a profile', () => {
    expect(matchSocialPath('/feed')).toEqual({ page: 'feed', id: null })
    expect(matchSocialPath('/feed/')).toEqual({ page: 'feed', id: null })
    expect(matchSocialPath('/feed/42')).toEqual({ page: 'feed', id: 42 })
    expect(matchSocialPath('/u/ann_9')).toEqual({ page: 'profile', handle: 'ann_9' })
    expect(matchSocialPath('/u/me')).toEqual({ page: 'profile', handle: 'me' })
  })
  it('rejects everything else', () => {
    for (const p of ['/', '/u', '/u/', '/u/a b', '/u/<img>', '/u/ann/x', '/feed/x', '/feed/1/2', '/trips/1', null, undefined]) {
      expect(matchSocialPath(p), String(p)).toBeNull()
    }
  })
  it('builds paths', () => {
    expect(profilePath('ann')).toBe('/u/ann')
    expect(feedPath(3)).toBe('/feed/3')
    expect(feedPath()).toBe('/feed')
  })
})
