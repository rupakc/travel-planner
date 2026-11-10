// Display words for backend enum values (confidence / coverage / severity
// levels). Only the label changes: logic keeps comparing the raw value.
import i18n from '../i18n'

/**
 * The translated word for `value` in `group` (`level`: high / medium / low,
 * `coverage`: excellent / good / moderate / limited, `severity`: info /
 * warning / danger / critical), or `value` unchanged when it isn't known.
 */
export function enumLabel(group, value) {
  if (typeof value !== 'string' || !value) return value
  const key = `common:enum.${group}.${value.toLowerCase()}`
  return i18n.exists(key) ? i18n.t(key) : value
}
