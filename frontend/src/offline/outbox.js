// Stub from Task 4 (frontend seams): Task 21 replaces this file with the
// per-user offline write queue. Final signatures; until then nothing queues.
export async function enqueue(userId, { method, path, body, key } = {}) {}
export async function flush(token, userId, fetchImpl) { return { sent: 0, failed: 0, dropped: 0 } }
export async function pending(userId) { return 0 }
export function startAutoFlush(getToken, getUserId) { return () => {} }
