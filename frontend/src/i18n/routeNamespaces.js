// Which English namespaces ship in the main bundle and which load per route.
//
// Bundled (always in memory, no wait):
//  - EAGER_NS, the core every screen may touch;
//  - SHELL_NS, what renders outside I18nRouteGate at first paint: the shell
//    (NavBar, account menu, footer, FeedbackWidget, alerts, game toasts,
//    banners), the always-mounted SearchTab (Search + Results) and ChatPage,
//    the routes outside the Layout (login, sign-up, share, onboarding), and the
//    pieces Phase 2 adds to those (Explore header, the drawer's completeness
//    meter, the coach marks).
// Lazy: LAZY_NS, used only inside I18nRouteGate. `index.js` repeats this list
// in two import.meta.glob patterns (globs must be literals); a test keeps them
// in step. A namespace nobody listed stays bundled, which is always safe.
import { matchTripPath } from '../journey/paths'

export const EAGER_NS = ['common', 'errors', 'auth', 'journey', 'offline', 'misc']

export const SHELL_NS = [
  'account', 'alerts', 'chat', 'coach', 'completeness', 'explore', 'game', 'itinerary',
  'oauth', 'onboarding', 'plan', 'privacy', 'profile', 'quota', 'recovery', 'results',
  'search', 'sections', 'signup', 'verify',
]

export const LAZY_NS = [
  'accountData', 'accountSettings', 'adminInvites', 'adminTelemetry', 'expenses', 'journal',
  'mobile', 'nearbyTrip', 'offlinePack', 'playYou', 'prep', 'recap', 'security', 'today',
  'trip', 'trips',
]

// Every tab of the trip screen, so moving between tabs never waits.
const TRIP_NS = ['trip', 'today', 'prep', 'completeness', 'offlinePack', 'expenses', 'journal', 'recap', 'game']

const ROUTES = {
  // `/` is the Trips hub for a signed-in user with a trip (journey on).
  '/': ['trips'],
  '/trips': ['trips'],
  '/explore': ['explore'],
  '/chat': ['chat'],
  '/nearby': ['nearbyTrip'],
  '/alerts': ['alerts'],
  '/preferences': ['account', 'alerts', 'search', 'privacy'],
  '/account': ['accountData', 'accountSettings', 'security', 'profile', 'quota', 'game', 'privacy', 'signup'],
  '/admin': ['adminInvites', 'adminTelemetry', 'account', 'signup'],
  '/play': ['playYou', 'game'],
  '/you': ['playYou', 'game', 'coach'],
  '/onboarding': ['onboarding'],
}

/** The namespaces the page at `pathname` renders with ([] for an unknown path). */
export function namespacesFor(pathname) {
  const path = String(pathname ?? '')
  if (Object.hasOwn(ROUTES, path)) return [...ROUTES[path]]
  return matchTripPath(path) ? [...TRIP_NS] : []
}
