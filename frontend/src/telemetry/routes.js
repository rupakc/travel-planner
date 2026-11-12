// Route templates for telemetry: a pathname becomes the route it matched, so
// share tokens, plan ids and anything else in the URL never leave the browser.

const STATIC = new Set([
  '/', '/chat', '/nearby', '/preferences', '/alerts', '/admin', '/login', '/change-password',
  '/account', '/signup', '/check-email', '/verify', '/forgot-password', '/reset-password',
  '/auth/callback', '/auth/username',
  '/trips', '/explore', '/play', '/you', '/onboarding', '/feed',
])

// [pattern, template]: the dynamic routes (and ones the plan reserves).
const DYNAMIC = [
  [/^\/share\/[^/]+$/, '/share/:token'],
  [/^\/plans\/[^/]+$/, '/plans/:id'],
  [/^\/alerts\/[^/]+$/, '/alerts/:id'],
  [/^\/trips\/[^/]+$/, '/trips/:id'],
  [/^\/trips\/[^/]+\/[^/]+$/, '/trips/:id/:tab'],
  [/^\/play\/h2h\/[^/]+$/, '/play/h2h/:id'],
  // Phase 5 social: a handle or idea id never leaves the browser.
  [/^\/u\/[^/]+$/, '/u/:handle'],
  [/^\/feed\/[^/]+$/, '/feed/:id'],
]

export function routeTemplate(pathname) {
  if (typeof pathname !== 'string' || pathname === '') return '/'
  const path = pathname.length > 1 ? pathname.replace(/\/+$/, '') || '/' : pathname
  if (STATIC.has(path)) return path
  for (const [re, template] of DYNAMIC) if (re.test(path)) return template
  return '/other'
}

export function currentRoute() {
  try {
    return routeTemplate(window.location.pathname)
  } catch {
    return '/'
  }
}
