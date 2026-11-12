import { describe, it, expect } from 'vitest'
import { tabsFor, resolveTabs, OFFLINE_TABS } from './tripTabs'
import { TRIP_TABS } from './paths'

describe('tabsFor', () => {
  it.each([
    ['dreaming', ['overview'], 'overview'],
    ['planning', ['overview', 'prep', 'money', 'offline'], 'overview'],
    ['ready', ['prep', 'overview', 'offline', 'money'], 'prep'],
    ['on_the_road', ['today', 'offline', 'money', 'journal', 'overview'], 'today'],
    ['memories', ['recap', 'journal', 'money', 'overview'], 'recap'],
  ])('%s', (phase, tabs, def) => {
    expect(tabsFor(phase)).toEqual({ tabs, default: def })
  })

  it('an unknown phase gets the Dreaming tabs, and callers cannot mutate the table', () => {
    expect(tabsFor('nope')).toEqual({ tabs: ['overview'], default: 'overview' })
    tabsFor('planning').tabs.push('journal')
    expect(tabsFor('planning').tabs).toEqual(['overview', 'prep', 'money', 'offline'])
  })

  it('every tab it names is a trip tab', () => {
    for (const phase of ['dreaming', 'planning', 'ready', 'on_the_road', 'memories']) {
      for (const tab of tabsFor(phase).tabs) expect(TRIP_TABS).toContain(tab)
    }
  })
})

describe('resolveTabs', () => {
  it('no tab in the URL opens the phase default', () => {
    expect(resolveTabs({ phase: 'on_the_road', tab: null })).toEqual({
      tabs: ['today', 'offline', 'money', 'journal', 'overview'],
      enabled: ['today', 'offline', 'money', 'journal', 'overview'],
      active: 'today',
    })
  })

  it('any trip tab stays reachable by URL, appended to the strip', () => {
    const r = resolveTabs({ phase: 'dreaming', tab: 'journal' })
    expect(r.tabs).toEqual(['overview', 'journal'])
    expect(r.active).toBe('journal')
  })

  it('offline: only Today and Offline are enabled', () => {
    expect(OFFLINE_TABS).toEqual(['today', 'offline'])
    const r = resolveTabs({ phase: 'on_the_road', tab: 'money', offline: true })
    expect(r.enabled).toEqual(['today', 'offline'])
    expect(r.active).toBe('offline')
    expect(resolveTabs({ phase: 'on_the_road', tab: null, offline: true }).active).toBe('today')
    expect(resolveTabs({ phase: 'on_the_road', tab: 'today', offline: true }).active).toBe('today')
  })

  it('offline in a phase without the Offline tab still shows it', () => {
    const r = resolveTabs({ phase: 'memories', tab: null, offline: true })
    expect(r.tabs).toEqual(['recap', 'journal', 'money', 'overview', 'offline'])
    expect(r.enabled).toEqual(['offline'])
    expect(r.active).toBe('offline')
  })

  it('offline_pack off: no Offline tab, and an offline-tab URL falls back to the phase default', () => {
    const r = resolveTabs({ phase: 'planning', offlinePack: false })
    expect(r.tabs).toEqual(['overview', 'prep', 'money'])
    expect(resolveTabs({ phase: 'ready', tab: 'offline', offlinePack: false })).toMatchObject({ active: 'prep' })
    expect(resolveTabs({ phase: 'on_the_road', offlinePack: false, offline: true })).toMatchObject({ tabs: ['today', 'money', 'journal', 'overview'], enabled: ['today'], active: 'today' })
  })
})
