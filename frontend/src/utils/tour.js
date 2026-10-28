// First-run tour: where to put the step card, and whether this user has
// already finished it.

const GAP = 12     // between the highlighted element and the card
const GUTTER = 16  // minimum distance from the viewport edge

const clamp = (n, min, max) => Math.min(Math.max(n, min), Math.max(min, max))

/**
 * Card position for a target's bounding rect (viewport coordinates).
 * Prefers below the target, then above; a target taller than the screen
 * gets the card over its bottom edge. No target → centred.
 */
export function placeTooltip(target, size, viewport) {
  if (!target) {
    return {
      placement: 'center',
      top: Math.round((viewport.height - size.height) / 2),
      left: Math.round((viewport.width - size.width) / 2),
    }
  }
  const left = Math.round(clamp(target.left, GUTTER, viewport.width - GUTTER - size.width))
  const below = target.bottom + GAP
  if (below + size.height <= viewport.height - GUTTER) return { placement: 'bottom', top: below, left }
  const above = target.top - GAP - size.height
  if (above >= GUTTER) return { placement: 'top', top: above, left }
  // On a very short screen the card may be taller than the space; keep its
  // top on screen (the card itself scrolls)
  return { placement: 'inside', top: Math.max(GUTTER, viewport.height - GUTTER - size.height), left }
}

// Completion is a per-browser convenience; blocked storage (private mode)
// just means the tour may be offered again.
export const tourDoneKey = (username) => `tp_tour_done:${username}`

export function isTourDone(username, storage = globalThis.localStorage) {
  try {
    return storage.getItem(tourDoneKey(username)) === '1'
  } catch {
    return false
  }
}

export function markTourDone(username, storage = globalThis.localStorage) {
  try {
    storage.setItem(tourDoneKey(username), '1')
  } catch {
    // not persisted
  }
}
