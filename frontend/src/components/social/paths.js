// Social URLs: /feed, /feed/<idea id> and /u/<handle> (/u/me is the own-profile editor).
const FEED_RE = /^\/feed(?:\/(\d{1,12}))?\/?$/
const PROFILE_RE = /^\/u\/([A-Za-z0-9_]{1,20})\/?$/
export const HANDLE_RE = /^[a-z0-9_]{3,20}$/i

/** '/feed' -> {page:'feed', id:null}; '/feed/7' -> {page:'feed', id:7}; '/u/ann' -> {page:'profile', handle:'ann'}; else null. */
export function matchSocialPath(pathname) {
  const p = String(pathname ?? '')
  const f = FEED_RE.exec(p)
  if (f) return { page: 'feed', id: f[1] ? Number(f[1]) : null }
  const u = PROFILE_RE.exec(p)
  if (u) return { page: 'profile', handle: u[1] }
  return null
}

export const profilePath = (handle) => `/u/${encodeURIComponent(handle)}`
export const feedPath = (id) => (id ? `/feed/${id}` : '/feed')
