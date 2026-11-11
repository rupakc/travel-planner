// The saved offline pack for (userId, tripId), reloaded whenever a pack is
// saved or deleted in this tab. -> {pack, savedAt, loading}.
import { useEffect, useState } from 'react'
import { getPack, PACKS_CHANGED_EVENT } from './packStore'

const empty = { pack: null, savedAt: null, loading: false }

export function useOfflinePack(userId, tripId) {
  const ready = userId !== null && userId !== undefined && tripId !== null && tripId !== undefined
  const [state, setState] = useState(() => (ready ? { ...empty, loading: true } : empty))

  useEffect(() => {
    if (!ready) { setState(empty); return undefined }
    let live = true
    const load = () => {
      getPack(userId, tripId).then(
        (pack) => { if (live) setState({ pack: pack || null, savedAt: pack?.saved_at || null, loading: false }) },
        () => { if (live) setState(empty) },
      )
    }
    setState((s) => ({ ...s, loading: true }))
    load()
    window.addEventListener(PACKS_CHANGED_EVENT, load)
    return () => { live = false; window.removeEventListener(PACKS_CHANGED_EVENT, load) }
  }, [ready, userId, tripId])

  return state
}
