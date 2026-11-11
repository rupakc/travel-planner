import { useEffect, useState } from 'react'
import { putOnboarding } from '../services/accountApi'
import { announceGame } from '../game/announce'
import { isTourDone, markTourDone } from '../utils/tour'

/**
 * When to show a first-run tour.
 *
 * - Opens by itself once, `delayMs` after the page is `visible` and the user
 *   is `eligible` (e.g. has no search history yet), unless they finished it.
 * - Shows only while `visible`: navigating away mid-tour hides it without
 *   marking it done, so it starts over on return.
 * - `start()` replays it on request; `close()` marks it done for this user.
 * - `close({ done: true })` (finished, not skipped) also reports onboarding
 *   to the account (starter XP), fire-and-forget; a 404 or failure is ignored.
 */
export default function useFirstRunTour({ username, visible, eligible, delayMs, token, stepsCount }) {
  const [open, setOpen] = useState(false)

  useEffect(() => {
    if (!username || !visible || !eligible || isTourDone(username)) return undefined
    const timer = setTimeout(() => setOpen(true), delayMs)
    return () => clearTimeout(timer)
  }, [username, visible, eligible, delayMs])

  return {
    open: open && visible,
    start: () => setOpen(true),
    close: (result) => {
      if (username) markTourDone(username)
      if (result?.done === true && token && stepsCount) {
        try {
          Promise.resolve(putOnboarding(token, { step: Math.min(stepsCount, 5), done: true }))
            .then((res) => announceGame(res?.game))
            .catch(() => {})
        } catch { /* ignored */ }
      }
      setOpen(false)
    },
  }
}
