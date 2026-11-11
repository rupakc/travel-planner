import { useCallback, useEffect, useState } from 'react'
import { getGameMe } from '../../services/gameApi'
import { onGameAnnounce } from '../../game/announce'

// GET /game/me for the signed-in user. `me` stays null when signed out, while
// loading and when the game API is unavailable (404 from an old backend or
// GAME_ENABLED=false); any failure just hides the game, it never throws.
// A game announcement (an award landed somewhere) refreshes it.
export default function useGameMe(token, enabled = true) {
  const [me, setMe] = useState(null)
  const [tick, setTick] = useState(0)
  const active = !!token && enabled

  useEffect(() => {
    if (!active) { setMe(null); return undefined }
    let live = true
    getGameMe(token).then(
      (data) => { if (live) setMe(data && typeof data === 'object' ? data : null) },
      () => { if (live) setMe(null) },
    )
    return () => { live = false }
  }, [active, token, tick])

  useEffect(() => {
    if (!active) return undefined
    return onGameAnnounce(() => setTick((n) => n + 1))
  }, [active])

  const reload = useCallback(() => setTick((n) => n + 1), [])
  return { me: active ? me : null, reload }
}

// Share of the way from this level's floor to the next one, 0..1.
export function levelProgress(me) {
  if (!me) return 0
  const { xp, level_min_xp: lo, next_level_xp: hi } = me
  if (hi == null || hi <= lo) return 1
  return Math.min(1, Math.max(0, (xp - lo) / (hi - lo)))
}
