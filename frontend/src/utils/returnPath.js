/**
 * Where to go after signing in. Only paths on this site are followed — a
 * crafted `?next=https://elsewhere` or `//elsewhere` falls back to home.
 */
const BASE = 'https://app.invalid'

export function safeReturnPath(raw) {
  if (typeof raw !== 'string' || !raw.startsWith('/') || raw.startsWith('//') || raw.startsWith('/\\')) return '/'
  let url
  try { url = new URL(raw, BASE) } catch { return '/' }
  if (url.origin !== BASE) return '/'
  const path = url.pathname
  if (path.startsWith('//') || path === '/login' || path.startsWith('/login/')) return '/'
  // An encoded "//host" would become protocol-relative once decoded by a router
  if (/^\/%2f/i.test(raw) || /^\/%5c/i.test(raw)) return '/'
  return `${path}${url.search}${url.hash}`
}

/** The login URL for a page that needed a signed-in user. */
export function loginPathFor(location) {
  const target = `${location.pathname || '/'}${location.search || ''}${location.hash || ''}`
  return target === '/' ? '/login' : `/login?next=${encodeURIComponent(target)}`
}

/** The page to return to from the login page's location. */
export function returnPathFrom(location) {
  const next = new URLSearchParams(location.search || '').get('next')
  if (next) return safeReturnPath(next)
  const from = location.state?.from
  if (from?.pathname) return safeReturnPath(`${from.pathname}${from.search || ''}${from.hash || ''}`)
  return '/'
}
