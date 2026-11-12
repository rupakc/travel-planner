import { useEffect, useRef } from 'react'

const FOCUSABLE = 'a[href],button:not([disabled]),input:not([disabled]),select:not([disabled]),textarea:not([disabled]),[tabindex]:not([tabindex="-1"])'

/**
 * Modal shell for the social dialogs: Escape and the backdrop close it, Tab
 * stays inside, focus returns to the opener. Props: titleId, tid, onClose, children.
 */
export default function SocialDialog({ titleId, tid, onClose, children }) {
  const ref = useRef(null)

  useEffect(() => {
    const opener = document.activeElement
    return () => { if (opener && opener !== document.body && opener.isConnected) opener.focus?.() }
  }, [])

  useEffect(() => {
    ref.current?.focus()
    const onKey = (e) => {
      if (e.key === 'Escape') { e.stopPropagation(); e.preventDefault(); onClose?.(); return }
      if (e.key !== 'Tab' || !ref.current) return
      const items = [...ref.current.querySelectorAll(FOCUSABLE)]
      if (!items.length) return
      const first = items[0]; const last = items[items.length - 1]
      const active = document.activeElement
      if (e.shiftKey && (active === first || active === ref.current)) { e.preventDefault(); last.focus() }
      else if (!e.shiftKey && active === last) { e.preventDefault(); first.focus() }
    }
    window.addEventListener('keydown', onKey, true)
    return () => window.removeEventListener('keydown', onKey, true)
  }, [onClose])

  return (
    <div className="fixed inset-0 z-[80] flex items-end justify-center bg-black/50 p-0 sm:items-center sm:p-4"
      data-tid={`${tid}.backdrop`} onClick={(e) => { if (e.target === e.currentTarget) onClose?.() }}>
      <div ref={ref} role="dialog" aria-modal="true" aria-labelledby={titleId} tabIndex={-1} data-tid={tid}
        className="max-h-[92vh] w-full max-w-md space-y-3 overflow-y-auto rounded-t-2xl bg-surface-raised p-4 text-text shadow-xl outline-none sm:rounded-2xl">
        {children}
      </div>
    </div>
  )
}
