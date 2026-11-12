import { describe, it, expect, vi, afterEach } from 'vitest'
import { sharingEnabled, cardUrl, pageUrl, buildIntent, shareFiles, copyText } from './share'

afterEach(() => { vi.unstubAllGlobals() })

describe('share utils', () => {
  it('sharingEnabled feature-detects features.sharing', () => {
    expect(sharingEnabled({ features: { sharing: 1 } })).toBe(true)
    expect(sharingEnabled({ features: { sharing: 0 } })).toBe(false)
    expect(sharingEnabled({ features: {} })).toBe(false)
    expect(sharingEnabled({})).toBe(false)
    expect(sharingEnabled(null)).toBe(false)
  })
  it('builds card and page urls', () => {
    expect(cardUrl('abc', 'story')).toBe('/api/share/abc/card.png?size=story')
    expect(cardUrl('abc')).toBe('/api/share/abc/card.png?size=link')
    expect(cardUrl('abc', 'huge')).toContain('size=link')
    expect(pageUrl('abc', 'https://x.io')).toBe('https://x.io/share/abc')
  })
  it('builds intents and encodes', () => {
    const o = { url: 'https://x.io/share/a?b=1', text: 'Hi & bye' }
    expect(buildIntent('x', o)).toBe('https://twitter.com/intent/tweet?url=https%3A%2F%2Fx.io%2Fshare%2Fa%3Fb%3D1&text=Hi%20%26%20bye')
    expect(buildIntent('facebook', o)).toContain('u=https%3A%2F%2Fx.io')
    expect(buildIntent('whatsapp', o)).toContain('wa.me/?text=Hi%20%26%20bye%20https')
    expect(buildIntent('linkedin', o)).toContain('url=https%3A%2F%2Fx.io')
    expect(buildIntent('copy', o)).toBeNull()
    expect(buildIntent('x', {})).toBeNull()
  })
  it('shareFiles throws when unsupported, shares link without file support', async () => {
    vi.stubGlobal('navigator', {})
    await expect(shareFiles({ url: 'u' })).rejects.toThrow('share_unsupported')
    const share = vi.fn().mockResolvedValue()
    vi.stubGlobal('navigator', { share })
    expect(await shareFiles({ url: 'u', text: 't', blob: new Blob(['x']) })).toBe('native')
    expect(share).toHaveBeenCalledWith({ url: 'u', text: 't', title: undefined })
  })
  it('shareFiles attaches the image when canShare allows it, null on abort', async () => {
    const share = vi.fn().mockResolvedValue()
    vi.stubGlobal('navigator', { share, canShare: () => true })
    await shareFiles({ url: 'u', blob: new Blob(['x']) })
    expect(share.mock.calls[0][0].files).toHaveLength(1)
    const abort = vi.fn().mockRejectedValue(Object.assign(new Error('x'), { name: 'AbortError' }))
    vi.stubGlobal('navigator', { share: abort })
    expect(await shareFiles({ url: 'u' })).toBeNull()
  })
  it('copyText reports failure instead of throwing', async () => {
    vi.stubGlobal('navigator', { clipboard: { writeText: vi.fn().mockRejectedValue(new Error('no')) } })
    expect(await copyText('a')).toBe(false)
    vi.stubGlobal('navigator', { clipboard: { writeText: vi.fn().mockResolvedValue() } })
    expect(await copyText('a')).toBe(true)
  })
})
