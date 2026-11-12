// Saved offline packs, per user: IndexedDB records keyed "<user_id>:<trip_id>"
// (see idb.js for the in-memory fallback). A stored pack is the server's
// OfflinePack plus `saved_at` (ISO time of the save). Sign-out deletes the
// user's packs (AuthContext → clearUser); features.offline_pack false deletes
// everyone's (registerSW.disableOffline → clearAllPacks).
import { idbGet, idbPut, idbDelete, idbEntries, idbDeletePrefix, storageMode as mode } from './idb'

const STORE = 'packs'
/** Window event fired after a pack is saved or deleted (useOfflinePack reloads). */
export const PACKS_CHANGED_EVENT = 'voyager:offline-packs-changed'

const userPrefix = (userId) => `${userId}:`
const keyOf = (userId, tripId) => `${userId}:${tripId}`

function notify() {
  try { window.dispatchEvent(new Event(PACKS_CHANGED_EVENT)) } catch { /* no window */ }
}

function requireUser(userId) {
  if (userId === null || userId === undefined || userId === '') throw new Error('offline packs need a user id')
}

/** Stores `pack` (needs `trip_id`) for the user; resolves with the stored record (pack + saved_at). */
export async function savePack(userId, pack) {
  requireUser(userId)
  if (!pack || pack.trip_id === null || pack.trip_id === undefined) throw new Error('savePack needs pack.trip_id')
  const record = { ...pack, saved_at: new Date().toISOString() }
  await idbPut(STORE, keyOf(userId, pack.trip_id), record)
  notify()
  return record
}

/** The stored pack (with `saved_at`), or null. */
export async function getPack(userId, tripId) {
  if (userId === null || userId === undefined || tripId === null || tripId === undefined) return null
  return idbGet(STORE, keyOf(userId, tripId))
}

/** Every stored pack of this user (each with `saved_at`). */
export async function listPacks(userId) {
  if (userId === null || userId === undefined) return []
  return (await idbEntries(STORE, userPrefix(userId))).map(([, v]) => v)
}

export async function deletePack(userId, tripId) {
  if (userId === null || userId === undefined) return
  await idbDelete(STORE, keyOf(userId, tripId))
  notify()
}

/** Deletes every pack of this user (sign-out, session_revoked). */
export async function clearUser(userId) {
  if (userId === null || userId === undefined) return
  await idbDeletePrefix(STORE, userPrefix(userId))
  notify()
}

/** Deletes every pack of every user (features.offline_pack false). */
export async function clearAllPacks() {
  await idbDeletePrefix(STORE, '')
  notify()
}

/** 'idb' (survives reloads) or 'memory' (only while this tab stays open). */
export function storageMode() {
  return mode()
}
