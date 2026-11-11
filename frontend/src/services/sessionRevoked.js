// The server answers 401 {"error_code": "session_revoked"} once this session's
// tokens were revoked elsewhere (password reset, sign out everywhere). Any API
// helper that sees it reports here; AuthContext listens and signs out.
const listeners = new Set()

export function reportSessionRevoked() {
  for (const fn of [...listeners]) fn()
}

export function onSessionRevoked(fn) {
  listeners.add(fn)
  return () => { listeners.delete(fn) }
}
