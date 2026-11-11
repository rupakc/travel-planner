// Stub from Task 4 (frontend seams): Task 21 replaces this file with the
// per-user IndexedDB pack store (records keyed "<user_id>:<trip_id>").
// Final signatures; until then nothing is stored.
export async function savePack(userId, pack) {}
export async function getPack(userId, tripId) { return null }
export async function listPacks(userId) { return [] }
export async function deletePack(userId, tripId) {}
export async function clearUser(userId) {}
export function storageMode() { return 'memory' }
