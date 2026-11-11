// Place keys (contract "Place key"): `<kind>:<slug>`. The slug is the name
// NFKD-normalised, combining marks removed, lower-cased, every run of
// non-[a-z0-9] replaced by `-`, trimmed of `-`, then cut to 60 characters;
// an empty slug is `x`. The vectors in
// backend/tests/fixtures/journey/place_key_cases.json pin this down for every
// client and the server.
export function placeKey(kind, name) {
  const slug = String(name ?? '')
    .normalize('NFKD')
    .replace(/\p{M}/gu, '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 60)
  return `${kind}:${slug || 'x'}`
}
