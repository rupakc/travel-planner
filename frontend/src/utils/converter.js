// Currency converter maths for the offline pack. `rate` is local units per 1
// home unit (the OfflinePack contract), so toLocal multiplies and toHome divides.
const ZERO = new Set(['JPY', 'KRW', 'VND', 'CLP', 'ISK', 'UGX', 'XAF', 'XOF'])
const THREE = new Set(['BHD', 'KWD', 'OMR', 'JOD', 'TND'])

export const exponentFor = (currency) => {
  const c = String(currency || '').toUpperCase()
  return ZERO.has(c) ? 0 : THREE.has(c) ? 3 : 2
}

/** Rounds `value` to the currency's minor-unit exponent (JPY -> whole yen). */
export function roundFor(currency, value) {
  const f = 10 ** exponentFor(currency)
  return Math.round(value * f + Number.EPSILON * Math.sign(value)) / f
}

/** -> number, unrounded; NaN when the inputs are not usable. */
export function convert(amount, rate, direction) {
  const a = Number(amount)
  const r = Number(rate)
  if (!Number.isFinite(a) || !Number.isFinite(r) || r <= 0) return NaN
  return direction === 'toHome' ? a / r : a * r
}
