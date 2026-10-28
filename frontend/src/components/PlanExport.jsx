import { useState } from 'react'
import { CalendarPlus, Printer } from 'lucide-react'
import { buildPlanIcs, planFileName, planItineraryDays } from '../utils/planExport'
import { buildPlanPrintHtml } from '../utils/planPrint'
import { countSelections } from '../utils/planHelpers'
import { track } from '../utils/analytics'

// Blob URLs must outlive the tab that loads them; a minute is plenty
const REVOKE_AFTER_MS = 60_000

function downloadFile(contents, type, fileName) {
  const url = URL.createObjectURL(new Blob([contents], { type }))
  const a = document.createElement('a')
  a.href = url
  a.download = fileName
  document.body.appendChild(a)
  a.click()
  a.remove()
  setTimeout(() => URL.revokeObjectURL(url), REVOKE_AFTER_MS)
}

/** "Add to calendar" (.ics) and "Print / PDF" buttons for the current plan. */
export default function PlanExport({ planName, planId = null, searchData, selections, itinerary = null, source, className = '' }) {
  const [message, setMessage] = useState(null)
  const hasItinerary = planItineraryDays(selections, itinerary).length > 0
  if (!countSelections(selections) && !hasItinerary) return null

  const exportCalendar = () => {
    const ics = buildPlanIcs({ planName, planId, searchData, selections, itinerary })
    downloadFile(ics, 'text/calendar;charset=utf-8', planFileName(planName, 'ics'))
    setMessage(null)
    track('plan_export', source, { format: 'ics' })
  }

  const openPrintView = () => {
    const html = buildPlanPrintHtml({ planName, searchData, selections, itinerary })
    const url = URL.createObjectURL(new Blob([html], { type: 'text/html;charset=utf-8' }))
    // Not 'noopener': that makes window.open return null even on success, so
    // a blocked tab couldn't be told apart. Cut the link back instead.
    const tab = window.open(url, '_blank')
    if (tab) {
      tab.opener = null
      setMessage(null)
    } else {
      setMessage('Your browser blocked the new tab — allow pop-ups for this site and try again.')
    }
    setTimeout(() => URL.revokeObjectURL(url), REVOKE_AFTER_MS)
    track('plan_export', source, { format: 'print' })
  }

  const buttonClass = 'flex-1 inline-flex items-center justify-center gap-1.5 px-3 py-2 text-xs font-medium text-teal-700 bg-teal-50 border border-teal-200 rounded-lg hover:bg-teal-100 transition-colors'

  return (
    <div className={className}>
      <div className="flex gap-2">
        <button type="button" onClick={exportCalendar} className={buttonClass}
          title="Download an .ics file for Google Calendar, Apple Calendar or Outlook">
          <CalendarPlus size={13} /> Add to calendar
        </button>
        <button type="button" onClick={openPrintView} className={buttonClass}
          title="Open a printable version you can print or save as a PDF">
          <Printer size={13} /> Print / PDF
        </button>
      </div>
      {message && <p role="status" className="mt-1.5 text-[11px] text-amber-700">{message}</p>}
    </div>
  )
}
