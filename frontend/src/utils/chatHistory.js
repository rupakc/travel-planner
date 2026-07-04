// Assistant turns produced by planning flows carry their answer in structured
// fields (sections / itinerary / trip map) with empty text content. The API
// rejects empty-content messages, and the model would otherwise have no memory
// of what it previously answered — so synthesize a text stand-in for history.
export function describeAssistantForApi(m) {
  if (m.content && m.content.trim()) return m.content
  const parts = []
  const it = m.comprehensiveItinerary
  if (it?.days?.length) {
    const dest = it.destination || it.trip_summary?.destination || ''
    const days = it.days.slice(0, 14).map(d =>
      `Day ${d.day_number}: ${(d.slots || []).map(s => s.activity).filter(Boolean).slice(0, 3).join('; ')}`
    ).join(' | ')
    parts.push(`[Shared a ${it.days.length}-day itinerary${dest ? ` for ${dest}` : ''} — ${days}]`)
  }
  if (m.tripMap?.cities?.length) {
    const route = m.tripMap.cities.map(c => c.city).filter(Boolean).join(' → ')
    const dates = m.tripMap.departure_date ? `, ${m.tripMap.departure_date} to ${m.tripMap.return_date || 'TBD'}` : ''
    parts.push(`[Trip route: ${route}${dates}]`)
  }
  const sectionKeys = Object.keys(m.sections || {})
  if (sectionKeys.length > 0) {
    parts.push(`[Shared search results for: ${sectionKeys.join(', ')}]`)
  }
  return parts.join('\n')
}

// Convert the on-screen message list into the sanitized history payload the
// backend expects: full past context, no empty-content entries.
export function buildApiHistory(messages) {
  return messages
    .map(m => ({
      role: m.role,
      content: m.role === 'assistant' ? describeAssistantForApi(m) : (m.content || ''),
    }))
    .filter(m => m.content && m.content.trim())
}
