import { describe, it, expect } from 'vitest'
import { EAGER_NS, SHELL_NS, LAZY_NS, namespacesFor } from './routeNamespaces'
import { NAMESPACES, BUNDLED_NAMESPACES } from './index'

// Every path the app routes to (App.jsx), on-demand and always-mounted.
const KNOWN_PATHS = [
  '/', '/chat', '/explore', '/nearby', '/alerts', '/preferences', '/account', '/admin',
  '/trips', '/trips/12', '/trips/12/overview', '/trips/12/prep', '/trips/12/today',
  '/trips/12/money', '/trips/12/journal', '/trips/12/recap', '/trips/12/offline',
  '/play', '/you', '/onboarding',
]
const routed = new Set(KNOWN_PATHS.flatMap(namespacesFor))

// Namespaces only the mobile apps read: the web never renders them.
const MOBILE_ONLY = ['mobile']

describe('route namespaces', () => {
  it('keeps the brief\'s eager core', () => {
    expect(EAGER_NS).toEqual(['common', 'errors', 'auth', 'journey', 'offline', 'misc'])
  })

  it('covers every namespace: eager, or loaded for at least one known path', () => {
    for (const ns of NAMESPACES) {
      const eager = EAGER_NS.includes(ns) || SHELL_NS.includes(ns)
      expect(eager || routed.has(ns) || MOBILE_ONLY.includes(ns), ns).toBe(true)
    }
  })

  it('bundles exactly the namespaces that are not lazy', () => {
    expect(BUNDLED_NAMESPACES).toEqual(NAMESPACES.filter((ns) => !LAZY_NS.includes(ns)))
    // A namespace someone adds later stays bundled (safe) but must be classified here.
    for (const ns of BUNDLED_NAMESPACES) {
      expect(EAGER_NS.includes(ns) || SHELL_NS.includes(ns), `${ns} is bundled but unclassified`).toBe(true)
    }
  })

  it('never makes a namespace both eager and lazy', () => {
    for (const ns of LAZY_NS) {
      expect(EAGER_NS, ns).not.toContain(ns)
      expect(SHELL_NS, ns).not.toContain(ns)
    }
  })

  it('loads every lazy namespace the web renders on some on-demand path', () => {
    for (const ns of LAZY_NS) {
      if (MOBILE_ONLY.includes(ns)) continue
      expect(routed.has(ns), ns).toBe(true)
    }
  })

  // R19: the persistent shell, the always-mounted SearchTab (Search + Results)
  // and ChatPage, and the routes outside the gate render before any route load.
  it('bundles what the shell and the always-mounted pages use', () => {
    for (const ns of [
      'search', 'results', 'sections', 'plan', 'itinerary', 'chat', 'alerts', 'game',
      'quota', 'profile', 'privacy', 'account', 'signup', 'verify', 'recovery', 'oauth',
      'explore', 'completeness', 'coach', 'onboarding',
    ]) expect(SHELL_NS, ns).toContain(ns)
  })

  it('maps the trip screen to all of its tabs\' namespaces', () => {
    expect(namespacesFor('/trips/12/today')).toEqual(
      ['trip', 'today', 'prep', 'completeness', 'offlinePack', 'expenses', 'journal', 'recap', 'game'],
    )
    expect(namespacesFor('/trips/12')).toEqual(namespacesFor('/trips/12/money'))
  })

  it('maps the on-demand pages', () => {
    expect(namespacesFor('/trips')).toContain('trips')
    expect(namespacesFor('/')).toContain('trips')
    expect(namespacesFor('/play')).toContain('playYou')
    expect(namespacesFor('/you')).toContain('playYou')
    expect(namespacesFor('/nearby')).toContain('nearbyTrip')
    expect(namespacesFor('/account')).toEqual(expect.arrayContaining(['accountData', 'accountSettings', 'security']))
    expect(namespacesFor('/admin')).toEqual(expect.arrayContaining(['adminInvites', 'adminTelemetry']))
  })

  it('returns nothing for an unknown path', () => {
    expect(namespacesFor('/nope')).toEqual([])
    expect(namespacesFor('/trips/12/bogus')).toEqual([])
    expect(namespacesFor(undefined)).toEqual([])
  })
})

// import.meta.glob needs literal patterns, so index.js repeats LAZY_NS twice.
import indexSource from './index.js?raw'
describe('index.js lazy globs', () => {
  it('list exactly LAZY_NS, both of them', () => {
    const lists = [...indexSource.matchAll(/locales\/en\/\{([^}]+)\}\.json/g)].map((m) => m[1].split(',').sort())
    expect(lists).toHaveLength(2)
    for (const list of lists) expect(list).toEqual([...LAZY_NS].sort())
  })
})
