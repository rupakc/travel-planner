// Walking-directions links. Apple Maps on iOS/iPadOS, Google Maps elsewhere.

const num = (n) => typeof n === 'number' && Number.isFinite(n)

/** True on iPhone, iPad and iPadOS (which reports a Mac UA with touch points). */
export function isApplePlatform(nav = typeof navigator === 'undefined' ? null : navigator) {
  if (!nav) return false
  const ua = String(nav.userAgent || '')
  return /iPhone|iPad|iPod/.test(ua) || (/Macintosh/.test(ua) && (nav.maxTouchPoints || 0) > 1)
}

export function directionsUrl({ lat, lng, name } = {}, { apple = false } = {}) {
  const dest = num(lat) && num(lng) ? `${lat},${lng}` : encodeURIComponent(String(name ?? ''))
  return apple
    ? `https://maps.apple.com/?daddr=${dest}&dirflg=w`
    : `https://www.google.com/maps/dir/?api=1&destination=${dest}&travelmode=walking`
}
