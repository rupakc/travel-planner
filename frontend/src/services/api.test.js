import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'

describe('getSerpapiConfigured', () => {
  let fetchMock

  beforeEach(() => {
    vi.resetModules()
    fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('reads /health once and caches the answer', async () => {
    fetchMock.mockResolvedValue({ ok: true, json: async () => ({ status: 'ok', serpapi_configured: true }) })
    const { getSerpapiConfigured } = await import('./api')
    expect(await getSerpapiConfigured()).toBe(true)
    expect(await getSerpapiConfigured()).toBe(true)
    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(fetchMock).toHaveBeenCalledWith('/health')
  })

  it('treats a missing flag as not configured', async () => {
    fetchMock.mockResolvedValue({ ok: true, json: async () => ({ status: 'ok' }) })
    const { getSerpapiConfigured } = await import('./api')
    expect(await getSerpapiConfigured()).toBe(false)
  })

  it('answers false on failure and asks again next time', async () => {
    fetchMock
      .mockRejectedValueOnce(new Error('offline'))
      .mockResolvedValueOnce({ ok: false, json: async () => ({}) })
      .mockResolvedValueOnce({ ok: true, json: async () => ({ serpapi_configured: true }) })
    const { getSerpapiConfigured } = await import('./api')
    expect(await getSerpapiConfigured()).toBe(false)
    expect(await getSerpapiConfigured()).toBe(false)
    expect(await getSerpapiConfigured()).toBe(true)
    expect(fetchMock).toHaveBeenCalledTimes(3)
  })

  it('exposes fare watch and email capabilities from the same read', async () => {
    fetchMock.mockResolvedValue({ ok: true, json: async () => ({ serpapi_configured: true, fare_watch_available: true, email_alerts_available: false }) })
    const { getCapabilities, getSerpapiConfigured } = await import('./api')
    expect(await getCapabilities()).toEqual({ serpapi: true, fareWatch: true, email: false })
    expect(await getSerpapiConfigured()).toBe(true)
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })
})
