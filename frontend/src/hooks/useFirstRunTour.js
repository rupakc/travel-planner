import { useEffect, useState } from 'react'
import { isTourDone, markTourDone } from '../utils/tour'

/**
 * When to show a first-run tour.
 *
 * - Opens by itself once, `delayMs` after the page is `visible` and the user
 *   is `eligible` (e.g. has no search history yet), unless they finished it.
 * - Shows only while `visible`: navigating away mid-tour hides it without
 *   marking it done, so it starts over on return.
 * - `start()` replays it on request; `close()` marks it done for this user.
 */
export default function useFirstRunTour({ username, visible, eligible, delayMs }) {
  const [open, setOpen] = useState(false)

  useEffect(() => {
    if (!username || !visible || !eligible || isTourDone(username)) return undefined
    const timer = setTimeout(() => setOpen(true), delayMs)
    return () => clearTimeout(timer)
  }, [username, visible, eligible, delayMs])

  return {
    open: open && visible,
    start: () => setOpen(true),
    close: () => {
      if (username) markTourDone(username)
      setOpen(false)
    },
  }
}
