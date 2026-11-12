const KEYS = ['emergency_card', 'forex', 'visa', 'packing_list', 'weather']

/** Sections worth freezing into a trip: present, no `error`, `verification` dropped; else null. */
export function snapshotFromResults(results) {
  const out = {}
  for (const key of KEYS) {
    const data = results?.[key]
    if (data && typeof data === 'object' && !Array.isArray(data) && !data.error) {
      const { verification: _v, ...rest } = data
      out[key] = rest
    } else {
      out[key] = null
    }
  }
  return out
}

export function hasSnapshotData(snapshot) {
  return KEYS.some((k) => snapshot?.[k])
}

const norm = (v) => String(v ?? '').trim().toLowerCase()

/** True when a search was started from this saved plan's search_data. */
export function searchMatchesPlan(searchData, plan) {
  const sd = plan?.search_data
  if (!searchData || !sd) return false
  return norm(searchData.destination) === norm(sd.destination)
    && norm(searchData.departure_date) === norm(sd.departure_date)
    && norm(searchData.origin) === norm(sd.origin)
    && norm(searchData.return_date) === norm(sd.return_date)
}
