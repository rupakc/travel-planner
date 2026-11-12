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
