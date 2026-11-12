// The savings share card: a 1080x1080 Canvas 2D drawing plus the share helper.
// Wording is "caught", never "saved"; only observed drops are counted, USD is
// the only summed currency (others are listed, never converted), and a deleted
// watch has no title so the "best catch" line then shows the amount alone.

export const CARD_SIZE = 1080

const num = (v) => (Number.isFinite(v) ? v : 0)

/**
 * Text lines of the card, from a (possibly minimal) savings object. `t` is an
 * i18next `savings`-namespace translate function and `fmt(amount, currency)`
 * formats money, so no amount is formatted here.
 */
export function savingsCardLines(savings, t, fmt) {
  const s = savings || {}
  const usd = num(s.total_usd)
  const headline = usd > 0
    ? t('card.headline', { amount: fmt(usd, 'USD') })
    : t('card.headlineOther')
  const sub = []
  if (num(s.drops_caught) > 0) sub.push(t('drops', { count: s.drops_caught }))
  if (num(s.targets_hit) > 0) sub.push(t('targets', { count: s.targets_hit }))
  const chips = Object.entries(s.by_currency || {})
    .filter(([, v]) => num(v) > 0)
    .map(([cur, v]) => fmt(v, cur))
  let best = null
  if (s.best && num(s.best.caught) > 0) {
    const amount = fmt(s.best.caught, s.best.currency || 'USD')
    best = s.best.title ? t('best', { title: s.best.title, amount }) : t('bestNoTitle', { amount })
  }
  return { headline, sub: sub.join(' · '), chips, best, footer: t('card.footer') }
}

function wrap(ctx, text, maxWidth) {
  const words = String(text).split(/\s+/)
  const lines = []
  let line = ''
  for (const w of words) {
    const next = line ? `${line} ${w}` : w
    if (line && ctx.measureText(next).width > maxWidth) { lines.push(line); line = w } else line = next
  }
  if (line) lines.push(line)
  return lines
}

const THEMES = {
  light: { bg: '#f0fdfa', fg: '#0f172a', muted: '#475569', accent: '#0f766e', chip: '#ccfbf1' },
  dark: { bg: '#042f2e', fg: '#f8fafc', muted: '#cbd5e1', accent: '#5eead4', chip: '#134e4a' },
}

/** Draws the card onto `ctx` (1080x1080). `strings` is the result of savingsCardLines. */
export function drawSavingsCard(ctx, savings, strings, theme = 'light') {
  const c = THEMES[theme] || THEMES.light
  const S = CARD_SIZE
  const st = strings || savingsCardLines(savings, (k) => k, (a, cur) => `${a} ${cur}`)
  ctx.fillStyle = c.bg
  ctx.fillRect(0, 0, S, S)
  ctx.fillStyle = c.accent
  ctx.fillRect(0, 0, S, 24)

  ctx.textAlign = 'left'
  ctx.textBaseline = 'alphabetic'
  ctx.fillStyle = c.fg
  ctx.font = '700 76px system-ui, sans-serif'
  let y = 300
  for (const line of wrap(ctx, st.headline, S - 160).slice(0, 4)) { ctx.fillText(line, 80, y); y += 96 }

  y += 20
  if (st.sub) {
    ctx.fillStyle = c.muted
    ctx.font = '500 44px system-ui, sans-serif'
    ctx.fillText(st.sub, 80, y)
    y += 80
  }
  let x = 80
  ctx.font = '600 38px system-ui, sans-serif'
  for (const chip of st.chips || []) {
    const w = ctx.measureText(chip).width + 48
    if (x + w > S - 80) { x = 80; y += 76 }
    ctx.fillStyle = c.chip
    ctx.fillRect(x, y - 44, w, 62)
    ctx.fillStyle = c.accent
    ctx.fillText(chip, x + 24, y)
    x += w + 16
  }
  if (st.chips?.length) y += 90
  if (st.best) {
    ctx.fillStyle = c.fg
    ctx.font = '500 40px system-ui, sans-serif'
    for (const line of wrap(ctx, st.best, S - 160).slice(0, 2)) { ctx.fillText(line, 80, y); y += 54 }
  }

  ctx.fillStyle = c.muted
  ctx.font = '400 32px system-ui, sans-serif'
  const foot = wrap(ctx, st.footer, S - 160).slice(0, 2)
  foot.forEach((line, i) => ctx.fillText(line, 80, S - 120 + i * 42))
  ctx.fillStyle = c.accent
  ctx.font = '700 44px system-ui, sans-serif'
  ctx.fillText('Voyager', 80, S - 190)
}

/**
 * Shares the card image. Returns 'native' (Web Share with a file), 'download'
 * (an image download) or 'copy' (text to the clipboard); null if the person
 * dismissed the native sheet. Throws only when no route works at all.
 */
export async function shareSavings(blob, text) {
  const nav = typeof navigator !== 'undefined' ? navigator : {}
  if (blob && typeof File !== 'undefined' && nav.share && nav.canShare) {
    try {
      const file = new File([blob], 'voyager-drops.png', { type: 'image/png' })
      if (nav.canShare({ files: [file] })) {
        await nav.share({ files: [file], text })
        return 'native'
      }
    } catch (e) {
      if (e?.name === 'AbortError') return null
    }
  }
  if (blob && typeof URL !== 'undefined' && URL.createObjectURL && typeof document !== 'undefined') {
    try {
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = 'voyager-drops.png'
      document.body.appendChild(a)
      a.click()
      a.remove()
      setTimeout(() => URL.revokeObjectURL?.(url), 1000)
      return 'download'
    } catch { /* fall through to copy */ }
  }
  await nav.clipboard.writeText(text)
  return 'copy'
}

/** Renders the card to a PNG blob (browser only). */
export function renderSavingsBlob(savings, strings, theme) {
  const canvas = document.createElement('canvas')
  canvas.width = CARD_SIZE
  canvas.height = CARD_SIZE
  drawSavingsCard(canvas.getContext('2d'), savings, strings, theme)
  return new Promise((resolve) => canvas.toBlob((b) => resolve(b), 'image/png'))
}
