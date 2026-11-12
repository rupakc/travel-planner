// Share helpers shared by the dialog and the entry points (Phase 4).
// Pure where possible; browser APIs are feature-detected.

export const SHARE_TARGETS = ['native', 'copy', 'download', 'x', 'facebook', 'whatsapp', 'linkedin']
export const SHARE_KINDS = ['plan', 'recap', 'savings']
export const DATES_MODES = ['hidden', 'month', 'exact']
export const DEFAULT_OPTIONS = Object.freeze({ dates: 'hidden', show_origin: false, show_name: false })

/** True when the backend's /api/config reports the new sharing (features.sharing >= 1). */
export function sharingEnabled(config) {
  const v = config?.features?.sharing
  return typeof v === 'number' ? v >= 1 : v === true
}

/** Card image URL for a token ('link' 1200x630 or 'story' 1080x1920). */
export function cardUrl(token, size = 'link') {
  const s = size === 'story' ? 'story' : 'link'
  return `/api/share/${encodeURIComponent(token)}/card.png?size=${s}`
}

/** Public page URL for a token, on this origin. */
export function pageUrl(token, origin) {
  const o = origin ?? (typeof window !== 'undefined' ? window.location.origin : '')
  return `${o}/share/${encodeURIComponent(token)}`
}

/** Web-intent URL for x / facebook / whatsapp / linkedin, or null for any other target. */
export function buildIntent(target, { url, text = '' } = {}) {
  if (!url) return null
  const u = encodeURIComponent(url)
  const tx = encodeURIComponent(text)
  switch (target) {
    case 'x': return `https://twitter.com/intent/tweet?url=${u}&text=${tx}`
    case 'facebook': return `https://www.facebook.com/sharer/sharer.php?u=${u}`
    case 'whatsapp': return `https://wa.me/?text=${encodeURIComponent(text ? `${text} ${url}` : url)}`
    case 'linkedin': return `https://www.linkedin.com/sharing/share-offsite/?url=${u}`
    default: return null
  }
}

/** True when the browser can show the native share sheet (links at least). */
export function canNativeShare() {
  return typeof navigator !== 'undefined' && typeof navigator.share === 'function'
}

/**
 * Native share. With a `blob` the card image is attached when the browser
 * supports sharing files, else the link alone is shared. Returns 'native',
 * or null when the person dismissed the sheet. Throws if sharing is unsupported.
 */
export async function shareFiles({ blob, url, text, title, filename = 'voyager-card.png' } = {}) {
  if (!canNativeShare()) throw new Error('share_unsupported')
  const nav = navigator
  try {
    if (blob && typeof File !== 'undefined' && nav.canShare) {
      const file = new File([blob], filename, { type: 'image/png' })
      if (nav.canShare({ files: [file] })) {
        await nav.share({ files: [file], text: text ? `${text} ${url}` : url, title })
        return 'native'
      }
    }
    await nav.share({ url, text, title })
    return 'native'
  } catch (e) {
    if (e?.name === 'AbortError') return null
    throw e
  }
}

/** Copies text; returns true on success, false when the browser refuses (caller then selects the field). */
export async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text)
    return true
  } catch { return false }
}

/** Saves a blob as a file download. */
export function downloadBlob(blob, filename) {
  const href = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = href
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  setTimeout(() => URL.revokeObjectURL?.(href), 1000)
}
