// Which tabs a trip screen shows, by phase, and which one opens first. Any tab
// in TRIP_TABS stays reachable by URL: a tab the phase doesn't list is added
// at the end of the strip while it is open.
import { TRIP_TABS } from './paths'

const TABLE = {
  dreaming: { tabs: ['overview'], default: 'overview' },
  planning: { tabs: ['overview', 'prep', 'money', 'offline'], default: 'overview' },
  ready: { tabs: ['prep', 'overview', 'offline', 'money'], default: 'prep' },
  on_the_road: { tabs: ['today', 'offline', 'money', 'journal', 'overview'], default: 'today' },
  memories: { tabs: ['recap', 'journal', 'money', 'overview'], default: 'recap' },
}

// Without a connection only these work (they read the saved pack).
export const OFFLINE_TABS = ['today', 'offline']

/** tabsFor(phase) -> {tabs: string[], default: string}; an unknown phase gets the Dreaming tabs. */
export function tabsFor(phase) {
  const row = TABLE[phase] ?? TABLE.dreaming
  return { tabs: [...row.tabs], default: row.default }
}

/**
 * The strip, the enabled tabs and the open tab for a phase, the URL's tab
 * (null: the phase default) and whether the trip came from the offline pack.
 * -> {tabs, enabled, active}
 */
export function resolveTabs({ phase, tab = null, offline = false }) {
  const { tabs, default: def } = tabsFor(phase)
  const wanted = tab && TRIP_TABS.includes(tab) ? tab : null
  if (wanted && !tabs.includes(wanted)) tabs.push(wanted)
  if (!offline) return { tabs, enabled: tabs, active: wanted ?? def }
  if (!tabs.includes('offline')) tabs.push('offline')
  const enabled = tabs.filter((t) => OFFLINE_TABS.includes(t))
  const first = wanted ?? def
  return { tabs, enabled, active: enabled.includes(first) ? first : 'offline' }
}
