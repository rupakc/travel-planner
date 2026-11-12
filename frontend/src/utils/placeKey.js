// Place keys (contract "Place key"): `<kind>:<slug>`. The slug is the name
// NFKD-normalised, combining marks removed, lower-cased, every run of
// non-[a-z0-9] replaced by `-`, trimmed of `-`, then cut to 60 characters; an
// empty slug is `x`. When the name still holds a non-ASCII letter or digit
// after that (CJK, Devanagari, Bengali, Arabic, ø, ß ...), distinct names
// would fold to the same slug, so the slug is cut to 51 characters, trimmed of
// `-`, (empty: `x`) and `-` plus 8 hex digits are appended: the FNV-1a 32-bit
// hash of the UTF-8 bytes of the NFC name with outer whitespace trimmed. The
// vectors in backend/tests/fixtures/journey/place_key_cases.json pin this down
// for every client and the server.
function fnv1a8(text) {
  let h = 0x811c9dc5
  for (const b of new TextEncoder().encode(text)) {
    h ^= b
    h = Math.imul(h, 0x01000193) >>> 0
  }
  return h.toString(16).padStart(8, '0')
}

export function placeKey(kind, name) {
  const raw = String(name ?? '')
  const folded = raw.normalize('NFKD').replace(/\p{M}/gu, '').toLowerCase()
  const slugOf = (max) => folded
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, max)
  if (/[^\x00-\x7f]/.test(folded.replace(/[^\p{L}\p{N}\x00-\x7f]/gu, ''))) {
    const base = slugOf(60).slice(0, 51).replace(/-+$/, '')
    return `${kind}:${base || 'x'}-${fnv1a8(raw.normalize('NFC').trim())}`
  }
  return `${kind}:${slugOf(60) || 'x'}`
}
