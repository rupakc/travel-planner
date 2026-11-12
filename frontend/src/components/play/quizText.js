// Localised bits of a quiz question. Prompts are templates (the `play`
// namespace); country names are localised from their ISO code, while
// capitals, landmarks and dishes ship in English.
export function regionName(code, fallback, lang) {
  try {
    const name = new Intl.DisplayNames([lang || 'en'], { type: 'region' }).of(String(code).toUpperCase())
    if (name && name !== String(code).toUpperCase()) return name
  } catch { /* unknown region or no Intl.DisplayNames */ }
  return fallback ?? String(code ?? '')
}

export const optionLabel = (opt, lang) => (opt.code ? regionName(opt.code, opt.label, lang) : opt.label)

export function promptText(t, prompt, lang) {
  switch (prompt?.template) {
    case 'capital_of':
      return t('quiz.prompt.capital_of', { country: regionName(prompt.code, prompt.country, lang) })
    case 'country_of_capital': return t('quiz.prompt.country_of_capital', { capital: prompt.capital })
    case 'landmark_country': return t('quiz.prompt.landmark_country', { landmark: prompt.landmark })
    case 'dish_country': return t('quiz.prompt.dish_country', { dish: prompt.dish })
    case 'flag': return t('quiz.prompt.flag')
    default: return ''
  }
}

/** Total XP of a finished session's summary (0 when none). */
export function xpEarned(summary) {
  const awards = summary?.xp?.awards
  return Array.isArray(awards) ? awards.reduce((n, a) => n + (Number(a?.points) || 0), 0) : 0
}
