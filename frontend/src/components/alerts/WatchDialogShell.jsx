import { useEffect, useId, useRef } from 'react'
import { createPortal } from 'react-dom'
import { X } from 'lucide-react'

/**
 * The frame every "Watch …" dialog shares (fares and price watches):
 * portalled modal with a title, a subtitle and a close button; Escape closes,
 * Tab / Shift+Tab stay inside, focus goes to the first field on open and
 * back to the opener on close. `children` is the dialog body.
 */
export default function WatchDialogShell({ title, subtitle, onClose, children }) {
  const titleId = useId()
  const dialogRef = useRef(null)

  // Escape closes; Tab / Shift+Tab cycle inside the dialog. Called from the
  // dialog's own onKeyDown (the portal stops key events from reaching the
  // document) and from a document listener when focus is outside it.
  const onKey = useRef(null)
  onKey.current = (e) => {
    if (e.key === 'Escape') { onClose(); return }
    if (e.key !== 'Tab' || !dialogRef.current) return
    const items = [...dialogRef.current.querySelectorAll(
      'button:not([disabled]), input:not([disabled]), a[href], [tabindex]:not([tabindex="-1"])',
    )]
    if (!items.length) return
    const first = items[0]
    const last = items[items.length - 1]
    const inside = dialogRef.current.contains(document.activeElement)
    if (e.shiftKey && (document.activeElement === first || !inside)) {
      e.preventDefault(); last.focus()
    } else if (!e.shiftKey && (document.activeElement === last || !inside)) {
      e.preventDefault(); first.focus()
    }
  }

  useEffect(() => {
    const opener = document.activeElement
    dialogRef.current?.querySelector('input,button')?.focus()
    const onDocKey = (e) => onKey.current(e)
    document.addEventListener('keydown', onDocKey)
    return () => {
      document.removeEventListener('keydown', onDocKey)
      if (opener && typeof opener.focus === 'function') opener.focus()
    }
  }, [])

  // Portalled and isolated: entry points live inside clickable headers
  return createPortal(
    <div className="fixed inset-0 z-[60] flex items-end justify-center sm:items-center sm:p-4"
      onClick={e => e.stopPropagation()} onKeyDown={e => { e.stopPropagation(); onKey.current(e) }}>
      <div className="absolute inset-0 bg-slate-900/40 backdrop-blur-[2px]" onClick={onClose} aria-hidden="true" />
      <div ref={dialogRef} role="dialog" aria-modal="true" aria-labelledby={titleId}
        className="relative max-h-[92vh] w-full overflow-y-auto rounded-t-2xl bg-white shadow-xl sm:max-w-md sm:rounded-2xl">
        <div className="flex items-start justify-between gap-3 px-5 pb-1 pt-5">
          <div className="min-w-0">
            <h2 id={titleId} className="text-base font-semibold text-slate-900">{title}</h2>
            {subtitle && <p className="mt-0.5 text-sm text-slate-500">{subtitle}</p>}
          </div>
          <button type="button" onClick={onClose} aria-label="Close"
            className="-mr-1 rounded-full p-1.5 text-slate-400 hover:bg-slate-100 hover:text-slate-600 focus-visible:outline focus-visible:outline-2 focus-visible:outline-sky-500">
            <X size={18} />
          </button>
        </div>
        {children}
      </div>
    </div>,
    document.body,
  )
}
