// Language tags of a place fact (docs/Place-Facts.md): `lang` is the
// language of the text as shown, `value_lang` the language of a quoted value
// in it (an official name, nickname or motto). Both are optional; an older
// backend sends neither.

const TAG = /^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{1,8})*$/

/** A BCP 47 tag worth putting in a `lang` attribute, else null ("und" too). */
export function langAttr(tag) {
  if (typeof tag !== 'string' || tag.length > 35 || !TAG.test(tag)) return null
  return tag.toLowerCase() === 'und' ? null : tag
}

/**
 * The text split around its one quoted value (“…”) when the fact names the
 * value's language, so the value can carry its own `lang`:
 * `{ before, value, after, lang }`, or null when there is nothing to mark.
 */
export function quotedValue(text, valueLang) {
  const lang = langAttr(valueLang)
  if (!lang || typeof text !== 'string') return null
  const open = text.indexOf('“')
  const close = open >= 0 ? text.indexOf('”', open + 1) : -1
  if (open < 0 || close < 0 || text.indexOf('“', close) >= 0) return null
  const value = text.slice(open + 1, close)
  if (!value.trim()) return null
  return { before: text.slice(0, open + 1), value, after: text.slice(close), lang }
}
