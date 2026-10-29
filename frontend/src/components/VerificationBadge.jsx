import { useCallback, useEffect, useId, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { BadgeCheck, CircleCheck, CircleX, Info, Loader2, ShieldAlert, ShieldQuestion, ExternalLink, Sparkles } from 'lucide-react'
import { safeUrl } from '../utils/planPrint'

// Per-level chip look. The chip is deliberately short (icon + short text) so
// section headers don't wrap on a phone; the full label is in the popover.
const LEVELS = {
  verified:   { text: 'Verified',   Icon: BadgeCheck,    chip: 'bg-emerald-50 text-emerald-700 border-emerald-200 hover:bg-emerald-100' },
  partial:    { text: 'Partly verified', Icon: ShieldQuestion, chip: 'bg-amber-50 text-amber-700 border-amber-200 hover:bg-amber-100' },
  unverified: { text: 'AI-generated', Icon: Sparkles,      chip: 'bg-gray-100 text-gray-600 border-gray-200 hover:bg-gray-200' },
  conflict:   { text: 'Check details', Icon: ShieldAlert,   chip: 'bg-rose-50 text-rose-700 border-rose-200 hover:bg-rose-100' },
}
const PENDING_CHIP = 'bg-amber-50 text-amber-700 border-amber-200 hover:bg-amber-100'
const CHECK_ICONS = {
  pass: { Icon: CircleCheck, cls: 'text-emerald-600', sr: 'Passed' },
  fail: { Icon: CircleX, cls: 'text-rose-600', sr: 'Failed' },
  info: { Icon: Info, cls: 'text-gray-400', sr: 'Note' },
}

const POPOVER_WIDTH = 288
const MARGIN = 8
const GAP = 6
const MAX_HEIGHT = 320
const MIN_BELOW = 200

// Fixed placement under the chip (flipped above when cramped), kept on screen.
function placement(rect, vw, vh) {
  const below = vh - rect.bottom - GAP - MARGIN
  const above = rect.top - GAP - MARGIN
  const up = below < MIN_BELOW && above > below
  const width = Math.min(POPOVER_WIDTH, vw - 2 * MARGIN)
  const left = Math.max(MARGIN, Math.min(rect.right - width, vw - MARGIN - width))
  const maxHeight = Math.max(0, Math.min(MAX_HEIGHT, up ? above : below))
  return up
    ? { position: 'fixed', left, width, maxHeight, bottom: vh - rect.top + GAP }
    : { position: 'fixed', left, width, maxHeight, top: rect.bottom + GAP }
}

const offScreen = (r) => r.bottom < 0 || r.top > window.innerHeight || r.right < 0 || r.left > window.innerWidth
const FOCUSABLE = 'a[href], button:not([disabled])'

// Portalled to <body> with fixed positioning because section cards clip
// (overflow-hidden) and keep a transform from their entry animation. Follows
// the chip on scroll/resize and closes when the chip leaves the viewport.
function Popover({ id, verification, anchorRef, onClose, onDismiss }) {
  const ref = useRef(null)
  const [rect, setRect] = useState(() => anchorRef.current.getBoundingClientRect())

  useEffect(() => { ref.current?.focus({ preventScroll: true }) }, [])
  useEffect(() => {
    const inside = (node) => ref.current?.contains(node) || anchorRef.current?.contains(node)
    const onPress = (e) => { if (!inside(e.target)) onDismiss() }
    const onFocusIn = (e) => { if (e.target instanceof Node && !inside(e.target)) onDismiss() }
    let pending = false
    let frame = 0
    const follow = (e) => {
      if (e.type === 'scroll' && ref.current?.contains(e.target)) return
      if (pending) return
      pending = true
      frame = window.requestAnimationFrame(() => {
        pending = false
        const el = anchorRef.current
        if (!el) return
        const next = el.getBoundingClientRect()
        if (offScreen(next)) onDismiss()
        else setRect(next)
      })
    }
    document.addEventListener('pointerdown', onPress)
    document.addEventListener('mousedown', onPress)
    document.addEventListener('focusin', onFocusIn)
    document.addEventListener('scroll', follow, true)
    window.addEventListener('resize', follow)
    return () => {
      if (pending) window.cancelAnimationFrame(frame)
      document.removeEventListener('pointerdown', onPress)
      document.removeEventListener('mousedown', onPress)
      document.removeEventListener('focusin', onFocusIn)
      document.removeEventListener('scroll', follow, true)
      window.removeEventListener('resize', follow)
    }
  }, [anchorRef, onDismiss])

  const onKeyDown = (e) => {
    e.stopPropagation()
    if (e.key === 'Escape') {
      e.preventDefault()
      onClose()
      return
    }
    if (e.key !== 'Tab') return
    // Tab moves through the links; leaving either end closes the popover and
    // hands focus back to the chip.
    const items = [...ref.current.querySelectorAll(FOCUSABLE)]
    const active = document.activeElement
    const atStart = active === ref.current || active === items[0]
    const atEnd = items.length === 0 || active === items[items.length - 1]
    if (e.shiftKey ? atStart : atEnd) {
      e.preventDefault()
      onClose()
    }
  }

  const checks = Array.isArray(verification.checks) ? verification.checks : []
  const counted = verification.items_total != null && verification.items_verified != null
  return createPortal(
    <div ref={ref} id={id} role="dialog" aria-label={`Source verification: ${verification.label || ''}`}
      tabIndex={-1} onKeyDown={onKeyDown} onClick={(e) => e.stopPropagation()}
      style={placement(rect, window.innerWidth, window.innerHeight)}
      className="z-50 overflow-y-auto bg-white border border-gray-200 rounded-lg shadow-lg p-3 text-left text-xs text-gray-700 focus:outline-none">
      <p className="font-semibold text-sm text-gray-900">{verification.label}</p>
      {verification.summary && <p className="mt-1 text-gray-600">{verification.summary}</p>}
      {counted && <p className="mt-1 text-gray-500">{verification.items_verified} of {verification.items_total} items found online</p>}
      {checks.length > 0 && (
        <ul className="mt-2 space-y-2">
          {checks.map((c, i) => {
            const { Icon, cls, sr } = CHECK_ICONS[c.status] || CHECK_ICONS.info
            const href = safeUrl(c.url)
            return (
              <li key={i} className="flex items-start gap-2">
                <Icon size={14} className={`${cls} mt-0.5 shrink-0`} aria-hidden="true" />
                <div className="min-w-0">
                  <p className="font-medium text-gray-800"><span className="sr-only">{sr}: </span>{c.label}</p>
                  {c.detail && <p className="text-gray-500">{c.detail}</p>}
                  {href && (
                    <a href={href} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 text-indigo-600 hover:text-indigo-800 underline break-all">
                      <ExternalLink size={10} aria-hidden="true" /> Source
                    </a>
                  )}
                </div>
              </li>
            )
          })}
        </ul>
      )}
    </div>,
    document.body,
  )
}

export default function VerificationBadge({ verification }) {
  const [open, setOpen] = useState(false)
  const buttonRef = useRef(null)
  const id = useId()
  const close = useCallback(() => { setOpen(false); buttonRef.current?.focus({ preventScroll: true }) }, [])
  const dismiss = useCallback(() => setOpen(false), [])
  if (!verification || typeof verification !== 'object') return null

  const level = LEVELS[verification.level] || LEVELS.unverified
  const pending = verification.pending === true
  const Icon = pending ? Loader2 : level.Icon
  return (
    <span className="inline-flex shrink-0" onClick={(e) => e.stopPropagation()} onKeyDown={(e) => e.stopPropagation()}>
      <button ref={buttonRef} type="button" aria-expanded={open} aria-controls={open ? id : undefined} aria-haspopup="dialog"
        aria-label={pending ? 'Checking sources' : `${verification.label || level.text} — source details`}
        title={verification.label}
        onClick={() => setOpen((o) => !o)}
        className={`inline-flex items-center gap-1 whitespace-nowrap text-xs font-medium border px-2 py-0.5 rounded-full transition-colors ${pending ? PENDING_CHIP : level.chip}`}>
        <Icon size={11} className={pending ? 'animate-spin' : ''} aria-hidden="true" />
        <span>{pending ? 'Checking…' : (verification.label || level.text)}</span>
      </button>
      {open && <Popover id={id} verification={verification} anchorRef={buttonRef} onClose={close} onDismiss={dismiss} />}
    </span>
  )
}

// One-line rose banner for a section-level conflict (Visa / Emergency bodies).
export function VerificationConflictBanner({ verification }) {
  if (verification?.level !== 'conflict') return null
  const link = (verification.checks || []).map((c) => c.status === 'fail' ? safeUrl(c.url) : null).find(Boolean)
  return (
    <div role="alert" className="flex items-start gap-2 text-xs text-rose-800 bg-rose-50 border border-rose-200 rounded-lg px-3 py-2">
      <ShieldAlert size={14} className="shrink-0 mt-0.5" aria-hidden="true" />
      <span>
        {verification.summary}
        {link && <> <a href={link} target="_blank" rel="noopener noreferrer" className="underline font-medium">Official site</a></>}
      </span>
    </div>
  )
}

// Small "Found online" tag for items whose link was confirmed by enrichment.
export function FoundOnlineBadge({ item }) {
  if (item?.link_verified !== true) return null
  return (
    <span title="This listing was found online by name" className="inline-flex items-center gap-1 text-xs bg-emerald-50 text-emerald-700 border border-emerald-200 rounded-full px-2 py-0.5">
      <BadgeCheck size={10} aria-hidden="true" /> Found online
    </span>
  )
}
