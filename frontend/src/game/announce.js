// In-memory pub-sub for GameDelta payloads: API callers announce, the
// celebration component listens. A null or empty delta is ignored.
const listeners = new Set()

export function announceGame(delta) {
  if (!delta || typeof delta !== 'object') return
  const empty = !(delta.awards?.length) && !(delta.badges?.length) && !delta.level_up
  if (empty) return
  for (const fn of [...listeners]) fn(delta)
}

export function onGameAnnounce(fn) {
  listeners.add(fn)
  return () => { listeners.delete(fn) }
}
