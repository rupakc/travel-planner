// Money helpers for the expense log. Amounts travel as decimal strings; the
// currency's exponent (minor-unit digits) follows docs/Trips-API.md.
const ZERO = new Set(['JPY', 'KRW', 'VND', 'CLP', 'ISK', 'UGX', 'XAF', 'XOF'])
const THREE = new Set(['BHD', 'KWD', 'OMR', 'JOD', 'TND'])
export const MAX_AMOUNT = 1000000

export function currencyExponent(code) {
  const c = String(code || '').toUpperCase()
  if (ZERO.has(c)) return 0
  if (THREE.has(c)) return 3
  return 2
}

/** Typed text ("12,50", "1,234.50", "12.5") -> "12.50" style string, or null when invalid. */
export function toAmountString(input, currency) {
  let s = String(input ?? '').replace(/[\s  ']/g, '')
  if (!s) return null
  const comma = s.lastIndexOf(',')
  const dot = s.lastIndexOf('.')
  if (comma >= 0 && dot >= 0) {
    // The later separator is the decimal mark; the other groups thousands.
    const dec = Math.max(comma, dot)
    const group = comma > dot ? '.' : ','
    s = s.slice(0, dec).split(group).join('') + '.' + s.slice(dec + 1)
  } else if (comma >= 0) {
    if (s.indexOf(',') !== comma) return null
    s = s.replace(',', '.')
  }
  const m = /^(\d{1,7})(?:\.(\d+))?$/.exec(s)
  if (!m) return null
  const decimals = m[2] || ''
  if (decimals.length > currencyExponent(currency)) return null
  const n = Number(s)
  if (!(n > 0) || n > MAX_AMOUNT) return null
  const intPart = m[1].replace(/^0+(?=\d)/, '')
  return decimals ? `${intPart}.${decimals}` : intPart
}
