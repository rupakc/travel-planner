import { useEffect, useId, useRef, useState } from 'react'
import { useInRouterContext, useLocation } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { ChevronDown } from 'lucide-react'
import { useAuth } from '../../context/AuthContext'
import { getStory } from '../../services/alertsApi'
import { relativeTime } from '../../utils/fareWatch'
import { prefersReducedMotion } from './PriceChart'
import PriceStory from './PriceStory'

const VERDICT_STYLE = {
  great: 'bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-200',
  good: 'bg-emerald-50 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-200',
  typical: 'bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-200',
  high: 'bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-200',
}

// Reads `?watch=kind:id` from the router and reports a match once per link.
function DeepLink({ kind, id, onMatch }) {
  const { search } = useLocation()
  const handled = useRef(null)
  useEffect(() => {
    const want = new URLSearchParams(search).get('watch')
    if (!want || handled.current === search) return
    if (want === `${kind}:${id}`) { handled.current = search; onMatch() }
  }, [search, kind, id, onMatch])
  return null
}

/**
 * v2 additions under a watch card: the verdict chip, "checked N days ago" and
 * a "Price story" expander. `?watch=kind:id` expands it and scrolls to the
 * card. The story is read from stored data (no live price lookup).
 */
export default function WatchCardExtras({ watch }) {
  const { t } = useTranslation('alerts')
  const { t: tStory } = useTranslation('priceStory')
  const { token } = useAuth()
  const inRouter = useInRouterContext()
  const kind = watch.kind || 'flight'
  const panel = useId()
  const root = useRef(null)
  const [story, setStory] = useState(null)
  const [open, setOpen] = useState(false)
  const [version, setVersion] = useState(0)

  useEffect(() => {
    if (!token) return undefined
    let live = true
    getStory(token, kind, watch.id).then((s) => { if (live) setStory(s) }, () => {})
    return () => { live = false }
  }, [token, kind, watch.id, version, watch.last_checked_at])

  const reveal = () => {
    setOpen(true)
    requestAnimationFrame(() => {
      root.current?.closest('article')?.scrollIntoView?.({ block: 'start', behavior: prefersReducedMotion() ? 'auto' : 'smooth' })
    })
  }

  const verdict = story?.verdict
  const checked = watch.last_checked_at ? t('extras.checked', { when: relativeTime(watch.last_checked_at) }) : t('extras.pending')

  return (
    <div ref={root} data-testid="watch-extras" className="mt-3 border-t border-slate-100 pt-3 dark:border-slate-700">
      {inRouter && <DeepLink kind={kind} id={watch.id} onMatch={reveal} />}
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2 text-xs text-slate-600 dark:text-slate-300">
        {verdict && VERDICT_STYLE[verdict] && (
          <span data-testid="extras-verdict" className={`rounded-full px-2.5 py-1 font-semibold ${VERDICT_STYLE[verdict]}`}>
            {tStory(`verdict.${verdict}`)}
          </span>
        )}
        <span data-testid="extras-checked">{checked}</span>
        <button type="button" data-tid="alerts.story-toggle" aria-expanded={open} aria-controls={panel}
          onClick={() => setOpen((o) => !o)}
          className="ml-auto inline-flex min-h-[44px] items-center gap-1.5 rounded-lg px-3 font-medium text-teal-800 hover:bg-teal-50 dark:text-teal-300 dark:hover:bg-teal-950/40">
          {open ? t('extras.storyClose') : t('extras.storyOpen')}
          <ChevronDown className={`h-4 w-4 transition-transform motion-reduce:transition-none ${open ? 'rotate-180' : ''}`} aria-hidden="true" />
        </button>
      </div>
      {open && (
        <div id={panel} className="mt-2" data-testid="extras-story">
          {story
            ? <PriceStory story={story} onTargetSaved={() => setVersion((v) => v + 1)} />
            : <PriceStory kind={kind} watchId={watch.id} onTargetSaved={() => setVersion((v) => v + 1)} />}
        </div>
      )}
    </div>
  )
}
