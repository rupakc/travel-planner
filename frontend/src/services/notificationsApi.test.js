// @vitest-environment node
import { describe, it, expect, vi, beforeEach } from 'vitest'

const http = vi.hoisted(() => ({
  get: vi.fn(), put: vi.fn(),
  interceptors: { request: { use: vi.fn() }, response: { use: vi.fn() } },
}))
vi.mock('axios', () => ({ default: { create: () => http } }))

import { getNotificationSettings, putNotificationSettings } from './notificationsApi'

const auth = { headers: { Authorization: 'Bearer tok' } }

beforeEach(() => {
  for (const fn of ['get', 'put']) http[fn].mockReset().mockResolvedValue({ data: { ok: 1 } })
})

describe('notifications API', () => {
  it('reads the settings', async () => {
    expect(await getNotificationSettings('tok')).toEqual({ ok: 1 })
    expect(http.get).toHaveBeenLastCalledWith('/notification-settings', auth)
  })

  it('writes a patch', async () => {
    const patch = { daily_cap: 4 }
    expect(await putNotificationSettings('tok', patch)).toEqual({ ok: 1 })
    expect(http.put).toHaveBeenLastCalledWith('/notification-settings', patch, auth)
  })
})
