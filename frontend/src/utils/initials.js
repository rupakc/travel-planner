// Initials and a stable colour for the avatar placeholder.

function graphemes(text) {
  try {
    if (typeof Intl !== 'undefined' && Intl.Segmenter) {
      return [...new Intl.Segmenter(undefined, { granularity: 'grapheme' }).segment(text)].map((s) => s.segment)
    }
  } catch { /* fall back below */ }
  return Array.from(text)
}

/** Up to 2 initials (base letter of the first grapheme): the first of the first two words of the name (or the username). */
export function initials(displayName, username) {
  const name = String(displayName || '').trim()
  const handle = String(username || '').trim()
  if (!name && !handle) return '?'
  // A username is one token (`jane_doe` -> `J`); a display name splits on spaces.
  const words = name ? name.split(/\s+/) : [handle]
  const picked = words.slice(0, 2).map((w) => graphemes(w.normalize('NFC'))[0])
    // Indic vowel signs ride along in a grapheme (`দো`); the base letter is the initial.
    .map((g) => (g ? Array.from(g)[0] : g)).filter(Boolean)
  return picked.join('').toLocaleUpperCase() || '?'
}

/** A stable hue 0..359 from the username. */
export function avatarHue(username) {
  let h = 0
  for (const ch of String(username || '')) h = (h * 31 + ch.codePointAt(0)) >>> 0
  return h % 360
}
