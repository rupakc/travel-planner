// Only a same-origin OAuth path is ever navigated to. The URL parser folds dot
// segments (including %2e%2e) and treats a backslash as a slash, so the
// resolved path is what gets checked; the raw string must also be free of `..`
// and backslashes. Returns path + query, or null.
export function safeAuthStart(url) {
  if (typeof url !== 'string' || url.includes('..') || url.includes('\\')) return null
  try {
    const u = new URL(url, window.location.origin)
    if (u.origin !== window.location.origin || !u.pathname.startsWith('/api/auth/')) return null
    return u.pathname + u.search
  } catch {
    return null
  }
}
