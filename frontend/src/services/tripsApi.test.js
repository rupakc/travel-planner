// @vitest-environment node
import { describe, it, expect, vi, beforeEach } from 'vitest'

const http = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), patch: vi.fn(), put: vi.fn(), delete: vi.fn() }))
vi.mock('axios', () => ({ default: { create: () => http } }))
vi.mock('../utils/tripPhase', () => ({ localToday: () => '2026-11-12' }))

import * as api from './tripsApi'

const auth = { headers: { Authorization: 'Bearer tok' } }
const withToday = { ...auth, params: { today: '2026-11-12' } }
beforeEach(() => { for (const f of Object.values(http)) f.mockReset().mockResolvedValue({ data: { ok: 1 } }) })

describe('tripsApi', () => {
  it('every GET sends the local date as today', async () => {
    const gets = [
      [() => api.listTrips('tok'), '/trips'],
      [() => api.getTrip('tok', 12), '/trips/12'],
      [() => api.getTripStats('tok'), '/trips/stats'],
      [() => api.getPrep('tok', 12), '/trips/12/prep'],
      [() => api.getOfflinePack('tok', 12), '/trips/12/offline-pack'],
      [() => api.listExpenses('tok', 12), '/trips/12/expenses'],
      [() => api.listJournal('tok', 12), '/trips/12/journal'],
      [() => api.listPlaces('tok', 12), '/trips/12/places'],
      [() => api.listCheckins('tok', 12), '/trips/12/checkins'],
      [() => api.getRecap('tok', 12), '/trips/12/recap'],
    ]
    for (const [call, path] of gets) {
      expect(await call()).toEqual({ ok: 1 })
      expect(http.get).toHaveBeenLastCalledWith(path, withToday)
    }
  })

  it('writes go to the contract paths', async () => {
    await api.createTrip('tok', { title: 'Lisbon' })
    expect(http.post).toHaveBeenLastCalledWith('/trips', { title: 'Lisbon' }, auth)
    await api.patchTrip('tok', 12, { phase: null })
    expect(http.patch).toHaveBeenLastCalledWith('/trips/12', { phase: null }, auth)
    await api.deleteTrip('tok', 12)
    expect(http.delete).toHaveBeenLastCalledWith('/trips/12', auth)
    await api.setPrepItem('tok', 12, 'visa', true)
    expect(http.put).toHaveBeenLastCalledWith('/trips/12/prep/visa', { done: true }, auth)
    await api.putSnapshot('tok', 12, { forex: null })
    expect(http.put).toHaveBeenLastCalledWith('/trips/12/snapshot', { forex: null }, auth)
    await api.addExpense('tok', 12, { amount: '1.00' })
    expect(http.post).toHaveBeenLastCalledWith('/trips/12/expenses', { amount: '1.00' }, auth)
    await api.updateExpense('tok', 12, 5, { note: 'x' })
    expect(http.patch).toHaveBeenLastCalledWith('/trips/12/expenses/5', { note: 'x' }, auth)
    await api.deleteExpense('tok', 12, 5)
    expect(http.delete).toHaveBeenLastCalledWith('/trips/12/expenses/5', auth)
    await api.addJournal('tok', 12, { body: 'hi' })
    expect(http.post).toHaveBeenLastCalledWith('/trips/12/journal', { body: 'hi' }, auth)
    await api.updateJournal('tok', 12, 7, { mood: 'ok' })
    expect(http.patch).toHaveBeenLastCalledWith('/trips/12/journal/7', { mood: 'ok' }, auth)
    await api.deleteJournal('tok', 12, 7)
    expect(http.delete).toHaveBeenLastCalledWith('/trips/12/journal/7', auth)
    await api.putPlace('tok', 12, 'activity:pasteis-de-belem', { name: 'P', kind: 'activity' })
    expect(http.put).toHaveBeenLastCalledWith(
      '/trips/12/places/activity%3Apasteis-de-belem', { name: 'P', kind: 'activity' }, auth)
    await api.deletePlace('tok', 12, 'place:x')
    expect(http.delete).toHaveBeenLastCalledWith('/trips/12/places/place%3Ax', auth)
  })

  it('check-in and recap completion send the local date too', async () => {
    await api.checkIn('tok', 12, '2026-11-12')
    expect(http.post).toHaveBeenLastCalledWith('/trips/12/checkin', { day: '2026-11-12' }, withToday)
    await api.completeRecap('tok', 12)
    expect(http.post).toHaveBeenLastCalledWith('/trips/12/recap/complete', null, withToday)
  })

  it('maps a 404 to trip_not_found', async () => {
    http.get.mockRejectedValue({ response: { status: 404, data: { detail: 'Trip not found', error_code: 'trip_not_found' }, headers: {} } })
    await expect(api.getTrip('tok', 99)).rejects.toMatchObject({ status: 404, code: 'trip_not_found', detail: 'Trip not found' })
  })

  it('a network failure rejects with code network', async () => {
    http.get.mockRejectedValue(Object.assign(new Error('Network Error'), { code: 'ERR_NETWORK' }))
    await expect(api.listTrips('tok')).rejects.toMatchObject({ status: 0, code: 'network' })
  })

  it('keeps a server error without a code as code null', async () => {
    http.get.mockRejectedValue({ response: { status: 500, data: {}, headers: {} } })
    await expect(api.listTrips('tok')).rejects.toMatchObject({ status: 500, code: null })
  })
})
