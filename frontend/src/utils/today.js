// Pure helpers for the Today view.

/** The slots of trip day `dayIndex` (1-based) from arranged (or scheduled) days. */
export function todaySlots(arrangedDays, dayIndex) {
  if (!Array.isArray(arrangedDays) || !Number.isInteger(dayIndex) || dayIndex < 1) return []
  const day = arrangedDays.find((d) => d?.day_number === dayIndex) ?? arrangedDays[dayIndex - 1]
  return Array.isArray(day?.slots) ? day.slots : []
}

const minutesOf = (hhmm) => {
  const m = /^(\d{1,2}):(\d{2})$/.exec(String(hhmm ?? ''))
  return m ? Number(m[1]) * 60 + Number(m[2]) : null
}

/** The first scheduled slot whose derived end is after `now` (local clock), or null. */
export function nextUp(scheduledSlots, now = new Date()) {
  const nowMin = now.getHours() * 60 + now.getMinutes()
  for (const slot of scheduledSlots ?? []) {
    const end = minutesOf(slot?.end_time)
    if (end === null) continue
    if (end + (slot.end_day_offset || 0) * 1440 > nowMin) return slot
  }
  return null
}
