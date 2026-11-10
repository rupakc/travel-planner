// Line wrapping for the share-card canvas. Wraps on spaces; a single token
// wider than the room (Chinese has no spaces, long URLs) is split per
// grapheme and its pieces are joined without inserting spaces.
// `measure(text)` returns the rendered width in px.

function graphemes(text) {
  try {
    if (typeof Intl !== 'undefined' && Intl.Segmenter) {
      return [...new Intl.Segmenter(undefined, { granularity: 'grapheme' }).segment(text)].map((s) => s.segment)
    }
  } catch { /* fall through */ }
  return Array.from(text)
}

export function wrapCanvasText(text, maxWidth, measure) {
  const out = []
  let cur = ''
  const flush = () => { if (cur) out.push(cur); cur = '' }
  for (const word of String(text).split(' ')) {
    const test = cur ? `${cur} ${word}` : word
    if (measure(test) <= maxWidth) { cur = test; continue }
    flush()
    if (measure(word) <= maxWidth) { cur = word; continue }
    // Token wider than a whole line: break it per grapheme
    for (const g of graphemes(word)) {
      if (cur && measure(cur + g) > maxWidth) flush()
      cur += g
    }
  }
  flush()
  return out.length ? out : ['']
}
