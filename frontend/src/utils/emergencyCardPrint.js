// HTML for the emergency-card print window. Every interpolated value (backend/AI
// text and translated strings) is escaped; links are limited to http(s) and tel:.
import i18n from '../i18n'
import { escapeHtml as esc, safeUrl } from './planPrint'

const tr = (key, opts) => esc(i18n.t(`results:${key}`, opts))

/** `tel:` link target for plain phone numbers only, else null. */
export function telHref(value) {
  const v = String(value ?? '').trim()
  return /^\+?\d[\d\s-]*$/.test(v) ? `tel:${v}` : null
}

function emergencyCardBodyHtml(card) {
  const numbers = card?.emergency_numbers || {}
  const phrases = card?.local_phrases || []
  const laws = card?.local_laws || []
  const hospitals = card?.hospitals || []
  const embassy = card?.embassy

  const lawsHtml = laws.map(l => `
    <div style="margin:4px 0;padding:6px 8px;border-radius:4px;background:${l.severity === 'critical' ? '#fee2e2' : '#fef3c7'};">
      <strong>${esc(l.law)}</strong>: ${esc(l.detail)}
    </div>`).join('')

  const phrasesHtml = phrases.map(p => `
    <tr>
      <td style="padding:4px 6px;border:1px solid #ddd;">${esc(p.english)}</td>
      <td style="padding:4px 6px;border:1px solid #ddd;">${esc(p.local)}</td>
      <td style="padding:4px 6px;border:1px solid #ddd;color:#555;">${esc(p.phonetic)}</td>
    </tr>`).join('')

  const phone = (v) => {
    const href = telHref(v)
    return href ? `<a href="${esc(href)}">${esc(v)}</a>` : esc(v)
  }
  const site = (v) => {
    const href = safeUrl(v)
    return href ? `<a href="${esc(href)}">${esc(v)}</a>` : esc(v)
  }

  return `
    <h2>${tr('emergency.numbers')}</h2>
    <div class="nums">
      <div class="num-box"><strong>${esc(numbers.police || '—')}</strong>${tr('emergency.police')}</div>
      <div class="num-box"><strong>${esc(numbers.ambulance || '—')}</strong>${tr('emergency.ambulance')}</div>
      <div class="num-box"><strong>${esc(numbers.fire || '—')}</strong>${tr('emergency.fire')}</div>
      <div class="num-box"><strong>${esc(numbers.tourist_police || '—')}</strong>${tr('emergency.touristPolice')}</div>
    </div>
    ${embassy ? `<h2>${tr('emergency.embassy')}</h2><p><strong>${esc(embassy.name)}</strong><br/>${esc(embassy.address)}<br/>📞 ${phone(embassy.phone)} | ${tr('emergency.afterHours', { value: embassy.emergency_after_hours || '—' })}<br/>🌐 ${site(embassy.website)} | ${esc(embassy.hours)}</p>` : ''}
    ${!embassy && card?.home_country_note ? `<p><em>${esc(card.home_country_note)}</em></p>` : ''}
    ${hospitals.length ? `<h2>${tr('emergency.hospitals')}</h2>${hospitals.map(h => `<p><strong>${esc(h.name)}</strong> — 📞 ${phone(h.phone)}<br/>${esc(h.address)}<br/><em>${esc(h.notes || '')}</em></p>`).join('')}` : ''}
    ${phrases.length ? `<h2>${tr('emergency.phrases')}</h2><table><tr><th>${tr('emergency.english')}</th><th>${tr('emergency.local')}</th><th>${tr('emergency.phonetic')}</th></tr>${phrasesHtml}</table>` : ''}
    ${laws.length ? `<h2>${tr('emergency.laws')}</h2>${lawsHtml}` : ''}`
}

/** Full document for the print window. `data` is one card or `{ cities: [card…] }`. */
export function buildEmergencyCardHtml({ data, destination }) {
  const cities = Array.isArray(data?.cities) ? data.cities : null
  const title = cities
    ? cities.map(c => (c.city || '').split(',')[0].trim()).filter(Boolean).join(' → ')
    : destination

  const bodyHtml = cities
    ? cities.map(c => `<div class="city-card"><h1 style="margin-top:18px">📍 ${esc(c.city)}</h1>${emergencyCardBodyHtml(c)}</div>`).join('<hr style="margin:16px 0;border:none;border-top:2px solid #ddd"/>')
    : emergencyCardBodyHtml(data)

  return `<!DOCTYPE html><html><head><title>${tr('emergency.cardTitle', { title })}</title>
    <style>
      body{font-family:Arial,sans-serif;max-width:700px;margin:20px auto;font-size:13px;color:#111}
      h1{font-size:17px;margin-bottom:4px} h2{font-size:13px;margin:12px 0 4px;border-bottom:1px solid #ccc;padding-bottom:2px}
      .nums{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin:8px 0}
      .num-box{background:#fee2e2;border-radius:6px;padding:8px;text-align:center}
      .num-box strong{display:block;font-size:18px;color:#991b1b}
      table{width:100%;border-collapse:collapse}
      td,th{border:1px solid #ddd;padding:4px 6px;font-size:12px}
      th{background:#f3f4f6;font-weight:600}
      .disclaimer{font-size:10px;color:#666;margin-top:16px;border-top:1px solid #ddd;padding-top:8px}
      @media print{button{display:none}}
    </style></head><body>
    <h1>🚨 ${tr('emergency.cardTitle', { title })}</h1>
    <p style="font-size:11px;color:#666;">${tr('emergency.verify')}</p>
    ${bodyHtml}
    <div class="disclaimer">${tr('emergency.disclaimer')}</div>
    <br/><button onclick="window.print()">🖨️ ${tr('emergency.printThis')}</button>
    </body></html>`
}
