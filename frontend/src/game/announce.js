// In-memory pub-sub for GameDelta payloads: API callers announce, the
// celebration component listens. A null or empty delta is ignored.
//
// Some awards arrive on public routes (/verify, the OAuth pages) just before
// the signed-in layout, and its celebration listener, mounts. A delta announced
// while no `replay` listener is mounted is kept for 15 s and handed, once, to
// the next listener that subscribes with `{ replay: true }`.
const REPLAY_MS = 15_000
const listeners = new Set()
const replayers = new Set()
let pending = null   // {delta, at}

export function announceGame(delta) {
  if (!delta || typeof delta !== 'object') return
  const empty = !(delta.awards?.length) && !(delta.badges?.length) && !delta.level_up
  if (empty) return
  pending = replayers.size ? null : { delta, at: Date.now() }
  for (const fn of [...listeners]) fn(delta)
}

export function onGameAnnounce(fn, { replay = false } = {}) {
  listeners.add(fn)
  if (replay) {
    replayers.add(fn)
    const held = pending
    pending = null
    if (held && Date.now() - held.at <= REPLAY_MS) fn(held.delta)
  }
  return () => { listeners.delete(fn); replayers.delete(fn) }
}
