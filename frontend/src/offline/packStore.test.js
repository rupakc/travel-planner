// jsdom has no IndexedDB, so idb.js runs on its in-memory map here.
import { describe, it, expect, beforeEach } from 'vitest'
import { savePack, getPack, listPacks, deletePack, clearUser, clearAllPacks, storageMode, PACKS_CHANGED_EVENT } from './packStore'
import { _resetForTests } from './idb'

const pack = (tripId, title = `Trip ${tripId}`) => ({ version: 1, trip_id: tripId, title })

beforeEach(() => { _resetForTests() })

describe('packStore', () => {
  it('runs on the in-memory store without IndexedDB', () => {
    expect(storageMode()).toBe('memory')
  })

  it('saves and reads a pack per user, stamped with saved_at', async () => {
    const saved = await savePack(7, pack(12))
    expect(saved.saved_at).toMatch(/Z$/)
    const got = await getPack(7, 12)
    expect(got.title).toBe('Trip 12')
    expect(got.saved_at).toBe(saved.saved_at)
    expect(await getPack(7, '12')).not.toBeNull()
    expect(await getPack(8, 12)).toBeNull()
    expect(await getPack(7, 99)).toBeNull()
  })

  it('a second save replaces the pack', async () => {
    await savePack(7, pack(12, 'old'))
    await savePack(7, pack(12, 'new'))
    expect((await getPack(7, 12)).title).toBe('new')
    expect(await listPacks(7)).toHaveLength(1)
  })

  it('lists only that user\'s packs (user 1 never sees user 12)', async () => {
    await savePack(1, pack(5))
    await savePack(12, pack(6))
    await savePack(12, pack(7))
    expect((await listPacks(1)).map((p) => p.trip_id)).toEqual([5])
    expect((await listPacks(12)).map((p) => p.trip_id).sort()).toEqual([6, 7])
  })

  it('deletes one pack, a whole user, or everything', async () => {
    await savePack(1, pack(5))
    await savePack(1, pack(6))
    await savePack(2, pack(5))
    await deletePack(1, 5)
    expect((await listPacks(1)).map((p) => p.trip_id)).toEqual([6])
    await clearUser(1)
    expect(await listPacks(1)).toEqual([])
    expect(await listPacks(2)).toHaveLength(1)
    await clearAllPacks()
    expect(await listPacks(2)).toEqual([])
  })

  it('announces changes so open views reload', async () => {
    let n = 0
    const on = () => { n += 1 }
    window.addEventListener(PACKS_CHANGED_EVENT, on)
    await savePack(1, pack(5))
    await deletePack(1, 5)
    window.removeEventListener(PACKS_CHANGED_EVENT, on)
    expect(n).toBe(2)
  })

  it('refuses a pack without trip_id', async () => {
    await expect(savePack(1, { title: 'x' })).rejects.toThrow()
  })
})
