import { useState } from 'react'
import { Link2 } from 'lucide-react'
import { Trans, useTranslation } from 'react-i18next'
import { safeUrl } from '../utils/planPrint'

// Marks anything that came from the link/text/screenshots the traveller
// imported. The amber "highlighter" colour is reserved for imported places
// across the app, so they read as the traveller's own picks at a glance.

const CHIP = 'inline-flex items-center gap-1 rounded-full bg-amber-100 text-amber-800 ring-1 ring-amber-200 px-2 py-0.5 text-[11px] font-semibold leading-none whitespace-nowrap'

export default function FromLinkChip({ quote, note, className = '' }) {
  const { t } = useTranslation('misc')
  const [open, setOpen] = useState(false)
  const detail = quote || note
  if (!detail) {
    return (
      <span className={`${CHIP} ${className}`}>
        <Link2 size={11} aria-hidden="true" />{t('fromLink.chip')}
      </span>
    )
  }
  return (
    <span className={`inline-flex flex-col items-start gap-1 ${className}`}>
      <button
        type="button"
        data-tid="from-link.toggle"
        className={`${CHIP} hover:bg-amber-200 focus:outline-none focus-visible:ring-2 focus-visible:ring-amber-500`}
        aria-expanded={open}
        title={quote ? `“${quote}”` : note}
        onClick={(e) => { e.stopPropagation(); setOpen((o) => !o) }}
      >
        <Link2 size={11} aria-hidden="true" />{t('fromLink.chip')}
      </button>
      {open && (
        <span className="block max-w-xs text-xs text-stone-600 leading-snug">
          {quote && <span className="italic bg-gradient-to-t from-amber-200/70 from-40% to-transparent to-40% px-0.5">“{quote}”</span>}
          {quote && note && <br />}
          {note}
        </span>
      )}
    </span>
  )
}

/** "Inspired by <title>" — links only http(s) URLs. */
export function InspiredBy({ source, className = '' }) {
  const { t } = useTranslation('misc')
  if (!source || !(source.title || source.url)) return null
  const href = safeUrl(source.url)
  const label = source.title || (href ? new URL(href).hostname.replace(/^www\./, '') : '')
  if (!label) return null
  return (
    <span className={`inline-flex items-center gap-1.5 ${className}`}>
      <Link2 size={13} aria-hidden="true" className="shrink-0" />
      <span>
        <Trans t={t} i18nKey="fromLink.inspiredBy" components={{
          src: href
            ? <a href={href} data-tid="from-link.source" target="_blank" rel="noopener noreferrer nofollow ugc" className="font-semibold underline decoration-amber-400 decoration-2 underline-offset-2 hover:decoration-amber-500">{label}</a>
            : <span className="font-semibold">{label}</span>,
        }} />
      </span>
    </span>
  )
}
