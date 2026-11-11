// The server answers 401 {"error_code": "session_revoked"} once this session's
// tokens were revoked elsewhere (password reset, sign out everywhere, a
// password change on another device). Every client funnels that answer here,
// with the token the failing request carried; AuthContext listens and decides
// (sign out with a notice, or adopt a fresher token another tab stored).
//
// Sources: every axios instance (watchAxios, one response interceptor each),
// every fetch on the main thread (watchFetch, installed once in main.jsx), and
// the SSE workers (their __error message carries status + code; the caller
// reports with the token it sent).
const listeners = new Set()

/** @param {string|null} [token] the bearer token the refused request used (null: unknown) */
export function reportSessionRevoked(token = null) {
  for (const fn of [...listeners]) fn(token || null)
}

export function onSessionRevoked(fn) {
  listeners.add(fn)
  return () => { listeners.delete(fn) }
}

export const isSessionRevoked = (status, body) =>
  status === 401 && !!body && typeof body === 'object' && body.error_code === 'session_revoked'

/** The bearer token in an axios/fetch headers value (plain object, AxiosHeaders or Headers). */
export function bearerToken(headers) {
  if (!headers) return null
  let value = null
  try {
    if (typeof headers.get === 'function') value = headers.get('Authorization') ?? headers.get('authorization')
    if (value == null) value = headers.Authorization ?? headers.authorization
  } catch { return null }
  const m = typeof value === 'string' ? /^Bearer\s+(.+)$/i.exec(value.trim()) : null
  return m ? m[1] : null
}

/** Adds the session_revoked response interceptor to an axios instance (returns it). */
export function watchAxios(instance) {
  if (typeof instance?.interceptors?.response?.use !== 'function') return instance   // stubbed in tests
  instance.interceptors.response.use(
    (res) => res,
    (err) => {
      const res = err?.response
      if (res && isSessionRevoked(res.status, res.data)) reportSessionRevoked(bearerToken(err.config?.headers))
      return Promise.reject(err)
    },
  )
  return instance
}

/**
 * Wraps `target.fetch` (once) so a 401 session_revoked from any direct fetch
 * caller is reported. The body is read from a clone, so callers still get an
 * unread response.
 */
export function watchFetch(target = globalThis) {
  const original = target?.fetch
  if (typeof original !== 'function' || original.__tpSessionWatch) return
  const wrapped = async function fetchWatched(input, init) {
    const res = await original.call(this ?? target, input, init)
    if (res && res.status === 401 && typeof res.clone === 'function') {
      const headers = init?.headers ?? (typeof input === 'object' && input ? input.headers : null)
      const token = bearerToken(headers)
      res.clone().json()
        .then((body) => { if (isSessionRevoked(401, body)) reportSessionRevoked(token) })
        .catch(() => {})
    }
    return res
  }
  wrapped.__tpSessionWatch = true
  target.fetch = wrapped
}
