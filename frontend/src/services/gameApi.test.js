// @vitest-environment node
import { describe, it, expect, vi } from 'vitest'

const http = vi.hoisted(() => ({ get: vi.fn() }))
vi.mock('axios', () => ({ default: { create: () => http } }))

import { getGameMe, getGameCatalog } from './gameApi'

describe('gameApi', () => {
  it('calls /game/me with bearer and /game/catalog without', async () => {
    http.get.mockResolvedValue({ data: { xp: 1 } })
    expect(await getGameMe('tok')).toEqual({ xp: 1 })
    expect(http.get).toHaveBeenLastCalledWith('/game/me', { headers: { Authorization: 'Bearer tok' } })
    await getGameCatalog()
    expect(http.get).toHaveBeenLastCalledWith('/game/catalog')
  })
  it('rejects with a normalised error', async () => {
    http.get.mockRejectedValue({ response: { status: 404, data: { detail: 'off' }, headers: {} } })
    await expect(getGameMe('t')).rejects.toMatchObject({ status: 404, detail: 'off' })
  })
})
