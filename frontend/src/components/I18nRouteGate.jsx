// Loads the English (and current-language) namespaces an on-demand route needs
// before rendering it, so a lazy namespace never shows raw keys. Waits only on
// lazy namespaces that exist: a page whose namespaces are all bundled renders
// at once, exactly as before. Shows a neutral skeleton while loading, and
// renders anyway after 3 s or when a chunk fails (better than a blank page).
import { Children, useEffect, useState } from 'react'
import i18n, { initI18n, NAMESPACES } from '../i18n'
import { LAZY_NS, namespacesFor } from '../i18n/routeNamespaces'

const GIVE_UP_MS = 3000

const isLoaded = (namespaces) =>
  i18n.isInitialized && namespaces.every((ns) => i18n.hasLoadedNamespace(ns))

// Visual placeholder only (hidden from assistive tech): it shows for a moment,
// and no eager namespace has a generic "Loading" string to announce.
function Skeleton() {
  return (
    <div data-tid="i18n.routeLoading" aria-hidden="true" className="max-w-5xl mx-auto px-4 py-8 space-y-4">
      <div className="h-8 w-48 rounded-lg bg-white/60 animate-pulse motion-reduce:animate-none" />
      <div className="h-32 rounded-2xl bg-white/60 animate-pulse motion-reduce:animate-none" />
    </div>
  )
}

export default function I18nRouteGate({ pathname, children }) {
  const namespaces = namespacesFor(pathname)
  const lazy = namespaces.filter((ns) => LAZY_NS.includes(ns) && NAMESPACES.includes(ns))
  const key = lazy.join(',')
  const all = namespaces.join(',')
  const ready = lazy.length === 0 || isLoaded(lazy)
  // Nothing to show on this path (e.g. `/` while Search is shown): no
  // skeleton, and no download.
  const empty = Children.toArray(children).length === 0
  // The key whose load finished, failed or timed out.
  const [settled, setSettled] = useState(null)

  useEffect(() => {
    if (ready || empty) return undefined
    let live = true
    const done = () => { if (live) setSettled(key) }
    const timer = setTimeout(done, GIVE_UP_MS)
    initI18n()
      .then(() => i18n.loadNamespaces(all.split(',')))
      .then(done, done)
    return () => { live = false; clearTimeout(timer) }
  }, [key, all, ready, empty])

  if (empty) return null
  if (ready || settled === key) return children
  return <Skeleton />
}
