// Helpers for the source-verification labels on search results.

const EVIDENCE_KEYS = ['link_verified', 'link_checked']
const GAVE_UP_SUMMARY = 'Link checks did not finish — verify before booking.'

// The stream ended (or the client gave up) while some sections were still
// awaiting URL enrichment: resolve their chip instead of spinning forever.
// Returns a new results object; untouched sections keep their identity.
export function clearPendingVerification(results) {
  if (!results || typeof results !== 'object') return results
  let changed = false
  const next = { ...results }
  for (const [key, section] of Object.entries(results)) {
    const v = section && typeof section === 'object' ? section.verification : null
    if (v?.pending === true) {
      next[key] = { ...section, verification: { ...v, pending: false, summary: GAVE_UP_SUMMARY } }
      changed = true
    }
  }
  return changed ? next : results
}

function stripItem(item) {
  if (!item || typeof item !== 'object' || Array.isArray(item)) return item
  if (!EVIDENCE_KEYS.some((k) => k in item)) return item
  const copy = { ...item }
  for (const k of EVIDENCE_KEYS) delete copy[k]
  return copy
}

// Saved plans store the chosen items, not this search's live link evidence.
export function stripLinkEvidence(selections) {
  if (!selections || typeof selections !== 'object') return selections
  const out = {}
  for (const [key, value] of Object.entries(selections)) {
    out[key] = Array.isArray(value) ? value.map(stripItem) : stripItem(value)
  }
  return out
}
