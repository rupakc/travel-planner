// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import i18n, { NAMESPACES } from '../i18n'
import I18nRouteGate from './I18nRouteGate'
import { LAZY_NS, namespacesFor } from '../i18n/routeNamespaces'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

let container, root
beforeEach(() => {
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
})
afterEach(() => {
  act(() => root.unmount())
  container.remove()
  vi.useRealTimers()
  vi.restoreAllMocks()
})

const render = (ui) => act(() => root.render(ui))
const skeleton = () => container.querySelector('[data-tid="i18n.routeLoading"]')
const child = () => container.querySelector('[data-testid="child"]')
const page = <div data-testid="child">page</div>

// Makes the route's namespaces look unloaded; returns the controls of the load.
function pendingLoad() {
  vi.spyOn(i18n, 'hasLoadedNamespace').mockReturnValue(false)
  let resolve, reject
  const load = vi.spyOn(i18n, 'loadNamespaces').mockImplementation(
    () => new Promise((res, rej) => { resolve = res; reject = rej }),
  )
  return { load, resolve: () => resolve(), reject: (e) => reject(e) }
}

describe('I18nRouteGate', () => {
  // A lazy namespace with no file yet (a later task adds it) never waits.
  const notYet = ['/nearby', '/trips', '/trips/3/today', '/play']
    .find((p) => namespacesFor(p).every((ns) => !LAZY_NS.includes(ns) || !NAMESPACES.includes(ns)))
  it.skipIf(!notYet)('does not wait on a lazy namespace that does not exist yet', () => {
    const ctl = pendingLoad()
    render(<I18nRouteGate pathname={notYet}>{page}</I18nRouteGate>)
    expect(child()).not.toBeNull()
    expect(ctl.load).not.toHaveBeenCalled()
  })

  it('renders children straight away when the namespaces are loaded', () => {
    const load = vi.spyOn(i18n, 'loadNamespaces')
    render(<I18nRouteGate pathname="/account">{page}</I18nRouteGate>)
    expect(child()).not.toBeNull()
    expect(skeleton()).toBeNull()
    expect(load).not.toHaveBeenCalled()
  })

  it('shows the skeleton, then its children', async () => {
    const ctl = pendingLoad()
    render(<I18nRouteGate pathname="/account">{page}</I18nRouteGate>)
    expect(skeleton()).not.toBeNull()
    expect(child()).toBeNull()
    await act(async () => {})
    expect(ctl.load).toHaveBeenCalledWith(namespacesFor('/account'))
    await act(async () => { ctl.resolve() })
    expect(skeleton()).toBeNull()
    expect(child()).not.toBeNull()
  })

  it('a rejected chunk still renders its children', async () => {
    const ctl = pendingLoad()
    render(<I18nRouteGate pathname="/account">{page}</I18nRouteGate>)
    expect(child()).toBeNull()
    await act(async () => {})
    await act(async () => { ctl.reject(new Error('chunk failed')) })
    expect(child()).not.toBeNull()
  })

  it('renders anyway after 3 s', async () => {
    vi.useFakeTimers()
    pendingLoad()
    render(<I18nRouteGate pathname="/admin">{page}</I18nRouteGate>)
    await act(async () => {})
    await act(async () => { vi.advanceTimersByTime(2900) })
    expect(child()).toBeNull()
    await act(async () => { vi.advanceTimersByTime(200) })
    expect(child()).not.toBeNull()
  })

  it('shows no skeleton when there is nothing to render', async () => {
    pendingLoad()
    render(<I18nRouteGate pathname="/">{false}{null}</I18nRouteGate>)
    expect(skeleton()).toBeNull()
    expect(container.innerHTML).toBe('')
  })

  // Flag-off pages whose namespaces are all bundled render exactly as before.
  it('never waits on a path whose namespaces are all bundled', () => {
    const ctl = pendingLoad()
    for (const path of ['/preferences', '/alerts', '/chat', '/nope']) {
      render(<I18nRouteGate pathname={path}>{page}</I18nRouteGate>)
      expect(child(), path).not.toBeNull()
      expect(skeleton(), path).toBeNull()
    }
    expect(ctl.load).not.toHaveBeenCalled()
  })
})
