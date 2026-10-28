import { useEffect, useId, useLayoutEffect, useRef, useState } from 'react'
import { placeTooltip } from '../utils/tour'

const SPOTLIGHT_PADDING = 6

// First element matching the selector that is actually laid out on screen
function findTarget(selector) {
  if (!selector) return null
  return [...document.querySelectorAll(selector)].find((el) => {
    const r = el.getBoundingClientRect()
    return r.width > 0 && r.height > 0
  }) || null
}

const prefersReducedMotion = () => window.matchMedia?.('(prefers-reduced-motion: reduce)').matches

/**
 * Step-by-step tooltip tour. Each step is { id, target, title, body }:
 * `target` is a CSS selector to highlight, or null for a centred card.
 * Steps whose element isn't on screen when the tour opens are skipped.
 */
export default function OnboardingTour({ open, steps, onClose }) {
  const [shown, setShown] = useState(null)
  const [index, setIndex] = useState(0)
  const [layout, setLayout] = useState({ spot: null, pos: null })
  const cardRef = useRef(null)
  const primaryRef = useRef(null)
  const onCloseRef = useRef(onClose)
  onCloseRef.current = onClose
  const titleId = useId()
  const bodyId = useId()

  // Decide which steps can be shown, and remember focus to restore later
  useEffect(() => {
    if (!open) return undefined
    const returnFocusTo = document.activeElement
    setShown(steps.filter((s) => !s.target || findTarget(s.target)))
    setIndex(0)
    return () => {
      setShown(null)
      returnFocusTo?.focus?.()
    }
  }, [open, steps])

  const step = shown?.[index]

  // Bring the target into view, then keep the spotlight and card on it —
  // through scrolling, resizing, and content shifting the page around
  useLayoutEffect(() => {
    if (!step) return undefined
    const target = findTarget(step.target)
    target?.scrollIntoView?.({ block: 'center', behavior: prefersReducedMotion() ? 'auto' : 'smooth' })

    const place = () => {
      const rect = target?.getBoundingClientRect() || null
      const card = cardRef.current?.getBoundingClientRect()
      const size = { width: card?.width || 320, height: card?.height || 180 }
      const viewport = { width: window.innerWidth, height: window.innerHeight }
      setLayout({ spot: rect, pos: placeTooltip(rect, size, viewport) })
    }
    let frame = 0
    const measure = () => {
      cancelAnimationFrame(frame)
      frame = requestAnimationFrame(place)
    }
    // Synchronously first, so a new step never paints at the old position
    place()
    window.addEventListener('resize', measure)
    window.addEventListener('scroll', measure, true)
    const observer = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(measure)
    observer?.observe(document.body)
    return () => {
      cancelAnimationFrame(frame)
      window.removeEventListener('resize', measure)
      window.removeEventListener('scroll', measure, true)
      observer?.disconnect()
    }
  }, [step])

  // The dialog is re-created per step (keyed by step id), so moving focus
  // into it makes screen readers announce the new title and text.
  // preventScroll: a focus-driven scroll would cancel the smooth scroll to
  // the step's element and strand the card off screen.
  useEffect(() => { if (step) primaryRef.current?.focus({ preventScroll: true }) }, [step])

  // Keys are handled on the document so Escape and the Tab trap keep working
  // even if focus has somehow left the card
  useEffect(() => {
    if (!step) return undefined
    const onKeyDown = (e) => {
      if (e.key === 'Escape') {
        e.preventDefault()
        onCloseRef.current()
      } else if (e.key === 'Tab') {
        const focusable = [...(cardRef.current?.querySelectorAll('button') || [])]
        if (!focusable.length) return
        const first = focusable[0]
        const last = focusable[focusable.length - 1]
        if (!cardRef.current.contains(document.activeElement)) {
          e.preventDefault()
          primaryRef.current?.focus({ preventScroll: true })
        } else if (e.shiftKey && document.activeElement === first) {
          e.preventDefault()
          last.focus()
        } else if (!e.shiftKey && document.activeElement === last) {
          e.preventDefault()
          first.focus()
        }
      }
    }
    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
  }, [step])

  if (!open || !step) return null

  const isLast = index === shown.length - 1
  const next = () => (isLast ? onClose() : setIndex(index + 1))

  const { spot, pos } = layout
  const showSpot = step.target && spot

  return (
    <div className="fixed inset-0 z-[60]">
      {/* Blocks the page while the tour is open (without taking focus);
          dims it when nothing is spotlit */}
      <div data-tour-backdrop aria-hidden="true" onMouseDown={(e) => e.preventDefault()}
        className={`absolute inset-0 ${showSpot ? '' : 'bg-slate-900/55'}`} />
      {showSpot && (
        <div aria-hidden="true"
          className="absolute rounded-xl ring-2 ring-teal-300 pointer-events-none transition-all duration-200 motion-reduce:transition-none"
          style={{
            top: spot.top - SPOTLIGHT_PADDING,
            left: spot.left - SPOTLIGHT_PADDING,
            width: spot.width + SPOTLIGHT_PADDING * 2,
            height: spot.height + SPOTLIGHT_PADDING * 2,
            boxShadow: '0 0 0 9999px rgba(15, 23, 42, 0.55)',
          }} />
      )}

      <div key={step.id} ref={cardRef} role="dialog" aria-modal="true" aria-labelledby={titleId} aria-describedby={bodyId}
        className="absolute w-[min(320px,calc(100vw-32px))] max-h-[calc(100vh-32px)] overflow-y-auto bg-white rounded-2xl shadow-2xl ring-1 ring-black/5 p-4"
        style={pos ? { top: pos.top, left: pos.left } : { top: '50%', left: '50%', transform: 'translate(-50%, -50%)' }}>
        <div className="flex items-start justify-between gap-3">
          <h2 id={titleId} className="font-semibold text-gray-900">{step.title}</h2>
          {shown.length > 1 && (
            <span className="shrink-0 text-[11px] font-medium text-gray-400 mt-0.5">{index + 1} of {shown.length}</span>
          )}
        </div>
        <p id={bodyId} className="mt-1.5 text-sm text-gray-600 leading-relaxed">{step.body}</p>

        <div className="mt-4 flex items-center gap-2">
          {!isLast && (
            <button type="button" onClick={onClose}
              className="mr-auto text-xs font-medium text-gray-400 hover:text-gray-600 focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-400 rounded px-1">
              Skip tour
            </button>
          )}
          {isLast && <span className="mr-auto" />}
          {index > 0 && (
            <button type="button" onClick={() => setIndex(index - 1)}
              className="px-3 py-1.5 text-sm font-medium text-gray-600 hover:text-gray-800 rounded-lg focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-400">
              Back
            </button>
          )}
          <button type="button" ref={primaryRef} onClick={next}
            className="px-3.5 py-1.5 text-sm font-semibold text-white bg-teal-600 hover:bg-teal-700 rounded-lg focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-400 focus-visible:ring-offset-2">
            {isLast ? 'Get started' : 'Next'}
          </button>
        </div>
      </div>
    </div>
  )
}
