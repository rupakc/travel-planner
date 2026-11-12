// Tiny IndexedDB key-value layer for the offline pack store and the outbox.
// One database (`voyager-offline`) with two object stores whose keys are
// strings beginning "<user_id>:". Without IndexedDB (jsdom, some private
// modes) everything runs on an in-memory map, which is what the tests use.
//
// The database is created only by a write. Reads, deletes and counts on a
// browser that never wrote anything answer empty without opening it, so a
// user who never saves a pack (or the classic shell with the journey off)
// gets no database at all. The marker tp_offline_db records that a write
// opened it.
const DB_NAME = 'voyager-offline'
const DB_VERSION = 1
export const STORES = ['packs', 'outbox']
const MARKER = 'tp_offline_db'

let dbPromise = null
let forcedMemory = false
let memory = new Map()

function idbAvailable() {
  try { return typeof indexedDB !== 'undefined' && !!indexedDB && typeof indexedDB.open === 'function' } catch { return false }
}

/** 'idb' when IndexedDB backs the stores, else 'memory' (lost on reload). */
export function storageMode() {
  return !forcedMemory && idbAvailable() ? 'idb' : 'memory'
}

function markerPresent() {
  try { return localStorage.getItem(MARKER) === '1' } catch { return true }
}
function setMarker() {
  try { localStorage.setItem(MARKER, '1') } catch { /* private mode */ }
}

/** The open IDBDatabase, or null in memory mode. Creates the database. */
export async function openDb() {
  if (storageMode() === 'memory') return null
  if (!dbPromise) {
    dbPromise = new Promise((resolve) => {
      let req
      const fallBack = () => { forcedMemory = true; dbPromise = null; resolve(null) }
      try { req = indexedDB.open(DB_NAME, DB_VERSION) } catch { fallBack(); return }
      req.onupgradeneeded = () => {
        const db = req.result
        for (const name of STORES) if (!db.objectStoreNames.contains(name)) db.createObjectStore(name)
      }
      req.onsuccess = () => {
        const db = req.result
        db.onversionchange = () => { db.close(); dbPromise = null }
        setMarker()
        resolve(db)
      }
      req.onerror = fallBack
    })
  }
  return dbPromise
}

// 'memory' | IDBDatabase | null (no database yet: nothing to read).
async function target(create) {
  if (storageMode() === 'memory') return 'memory'
  if (!create && !markerPresent()) return null
  const db = await openDb()
  return db || 'memory'
}

function memStore(store) {
  if (!memory.has(store)) memory.set(store, new Map())
  return memory.get(store)
}

const copy = (value) => {
  if (value === undefined) return undefined
  try { return structuredClone(value) } catch { return JSON.parse(JSON.stringify(value)) }
}

// Runs `fn(objectStore)` in one transaction; resolves when it commits with
// the last request's result.
function run(db, store, mode, fn) {
  return new Promise((resolve, reject) => {
    let tx
    try { tx = db.transaction(store, mode) } catch (err) { reject(err); return }
    let result
    const req = fn(tx.objectStore(store))
    if (req) req.onsuccess = () => { result = req.result }
    tx.oncomplete = () => resolve(result)
    tx.onerror = () => reject(tx.error)
    tx.onabort = () => reject(tx.error)
  })
}

const range = (prefix) => IDBKeyRange.bound(prefix, `${prefix}￿`)

export async function idbGet(store, key) {
  const t = await target(false)
  if (!t) return null
  if (t === 'memory') return copy(memStore(store).get(key)) ?? null
  return (await run(t, store, 'readonly', (os) => os.get(key))) ?? null
}

export async function idbPut(store, key, value) {
  const t = await target(true)
  if (t === 'memory') { memStore(store).set(key, copy(value)); return }
  await run(t, store, 'readwrite', (os) => os.put(value, key))
}

export async function idbDelete(store, key) {
  const t = await target(false)
  if (!t) return
  if (t === 'memory') { memStore(store).delete(key); return }
  await run(t, store, 'readwrite', (os) => os.delete(key))
}

/** [[key, value], …] for every key starting with `prefix`, in key order. */
export async function idbEntries(store, prefix) {
  const t = await target(false)
  if (!t) return []
  if (t === 'memory') {
    return [...memStore(store).entries()]
      .filter(([k]) => k.startsWith(prefix))
      .sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0))
      .map(([k, v]) => [k, copy(v)])
  }
  const out = []
  await run(t, store, 'readonly', (os) => {
    const req = os.openCursor(range(prefix))
    req.onsuccess = () => {
      const cursor = req.result
      if (!cursor) return
      out.push([cursor.key, cursor.value])
      cursor.continue()
    }
    return null
  })
  return out
}

export async function idbCount(store, prefix) {
  const t = await target(false)
  if (!t) return 0
  if (t === 'memory') return [...memStore(store).keys()].filter((k) => k.startsWith(prefix)).length
  return (await run(t, store, 'readonly', (os) => os.count(range(prefix)))) || 0
}

/** Deletes every key starting with `prefix` ('' deletes the whole store). */
export async function idbDeletePrefix(store, prefix) {
  const t = await target(false)
  if (!t) return
  if (t === 'memory') {
    const m = memStore(store)
    for (const k of [...m.keys()]) if (k.startsWith(prefix)) m.delete(k)
    return
  }
  await run(t, store, 'readwrite', (os) => (prefix ? os.delete(range(prefix)) : os.clear()))
}

export function _resetForTests() {
  memory = new Map()
  dbPromise = null
  forcedMemory = false
}
