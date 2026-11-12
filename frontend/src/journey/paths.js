// Journey URLs. A trip lives at /trips/<id> and its tabs at /trips/<id>/<tab>.
export const TRIP_TABS = ['overview', 'prep', 'today', 'money', 'journal', 'recap', 'offline']

export function tripPath(id, tab) {
  return tab ? `/trips/${id}/${tab}` : `/trips/${id}`
}

const TRIP_RE = /^\/trips\/(\d{1,12})(?:\/([a-z]+))?\/?$/

/** '/trips/3/today' -> {id: 3, tab: 'today'}; '/trips/3' -> {id: 3, tab: null}; else null. */
export function matchTripPath(pathname) {
  const m = TRIP_RE.exec(String(pathname ?? ''))
  if (!m) return null
  const tab = m[2] ?? null
  if (tab !== null && !TRIP_TABS.includes(tab)) return null
  return { id: Number(m[1]), tab }
}

const H2H_RE = /^\/play\/h2h\/([A-Za-z0-9_-]{1,64})\/?$/

/** '/play/h2h/abc' -> 'abc' (a head-to-head match page); else null. */
export function matchH2hPath(pathname) {
  const m = H2H_RE.exec(String(pathname ?? ''))
  return m ? m[1] : null
}
