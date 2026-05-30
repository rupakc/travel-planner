/**
 * offlineExport.js
 * Generate a self-contained, offline-capable HTML file from a travel plan.
 * No external dependencies — all CSS is inlined.
 */

/** Escape a string for safe insertion into HTML text content. */
function esc(str) {
  if (str === null || str === undefined) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');
}

// ---------------------------------------------------------------------------
// Section builders
// ---------------------------------------------------------------------------

/**
 * Build the itinerary section HTML from activities/days data.
 * Expects data to be an array of day objects:
 *   [{ day: 1, date: "...", title: "...", slots: [{ time, activity, notes }] }]
 */
function buildItinerary(data) {
  if (!data || !Array.isArray(data) || data.length === 0) {
    return '<p class="empty">No itinerary data available.</p>';
  }

  return data.map((day) => {
    const dayLabel = day.day ? `Day ${esc(day.day)}` : '';
    const dateLabel = day.date ? ` &mdash; ${esc(day.date)}` : '';
    const titleLabel = day.title ? `: ${esc(day.title)}` : '';

    const slots = Array.isArray(day.slots) ? day.slots : [];
    const slotRows = slots.length
      ? slots.map((s) => `
          <tr>
            <td class="time-cell">${esc(s.time || '')}</td>
            <td><strong>${esc(s.activity || '')}</strong>${s.notes ? `<br><span class="note">${esc(s.notes)}</span>` : ''}</td>
          </tr>`).join('')
      : '<tr><td colspan="2" class="empty">No activities listed.</td></tr>';

    return `
      <div class="card">
        <h3 class="section-sub">${dayLabel}${dateLabel}${titleLabel}</h3>
        <table class="slot-table">
          <tbody>${slotRows}</tbody>
        </table>
      </div>`;
  }).join('');
}

/**
 * Build the emergency contacts section HTML.
 * Expects data to be an object or array of { label, value } entries,
 * or a plain object where keys are labels and values are contact strings.
 */
function buildEmergency(data) {
  if (!data) return '<p class="empty">No emergency contact data available.</p>';

  let entries = [];
  if (Array.isArray(data)) {
    entries = data;
  } else if (typeof data === 'object') {
    entries = Object.entries(data).map(([label, value]) => ({ label, value }));
  }

  if (entries.length === 0) return '<p class="empty">No emergency contacts listed.</p>';

  const rows = entries.map((e) => `
    <tr>
      <td class="label-cell"><strong>${esc(e.label || e.name || '')}</strong></td>
      <td>${esc(e.value || e.number || e.phone || e.contact || '')}</td>
    </tr>`).join('');

  return `
    <div class="card emergency-card">
      <table class="info-table"><tbody>${rows}</tbody></table>
    </div>`;
}

/**
 * Build the travel tips section HTML.
 * Accepts an array of tip strings or objects with a { tip } / { text } field,
 * or an object with categorised arrays (e.g. { safety: [...], culture: [...] }).
 */
function buildTips(data) {
  if (!data) return '<p class="empty">No tips available.</p>';

  // Flat array of strings or { tip/text } objects
  if (Array.isArray(data)) {
    if (data.length === 0) return '<p class="empty">No tips available.</p>';
    const items = data.map((t) => {
      const text = typeof t === 'string' ? t : (t.tip || t.text || t.content || JSON.stringify(t));
      return `<li>${esc(text)}</li>`;
    }).join('');
    return `<div class="card"><ul class="tip-list">${items}</ul></div>`;
  }

  // Categorised object
  if (typeof data === 'object') {
    const sections = Object.entries(data).map(([category, tips]) => {
      const tipsArr = Array.isArray(tips) ? tips : [tips];
      const items = tipsArr.map((t) => {
        const text = typeof t === 'string' ? t : (t.tip || t.text || t.content || JSON.stringify(t));
        return `<li>${esc(text)}</li>`;
      }).join('');
      return `
        <div class="card">
          <h3 class="section-sub">${esc(category)}</h3>
          <ul class="tip-list">${items}</ul>
        </div>`;
    });
    return sections.join('');
  }

  return `<div class="card"><p>${esc(String(data))}</p></div>`;
}

/**
 * Build the local transport section HTML.
 * Accepts an array of transport option objects:
 *   [{ name, description, cost, notes }]
 */
function buildTransport(data) {
  if (!data || !Array.isArray(data) || data.length === 0) {
    return '<p class="empty">No transport data available.</p>';
  }

  return data.map((opt) => `
    <div class="card">
      <h3 class="section-sub">${esc(opt.name || opt.type || 'Transport option')}</h3>
      ${opt.description ? `<p>${esc(opt.description)}</p>` : ''}
      ${opt.cost ? `<p><span class="badge">Cost</span> ${esc(opt.cost)}</p>` : ''}
      ${opt.notes ? `<p class="note">${esc(opt.notes)}</p>` : ''}
    </div>`).join('');
}

/**
 * Build the SIM / eSIM section HTML.
 * Accepts an array of plan objects:
 *   [{ name, provider, data, price, notes }]
 */
function buildSim(data) {
  if (!data || !Array.isArray(data) || data.length === 0) {
    return '<p class="empty">No SIM plan data available.</p>';
  }

  return data.map((plan) => `
    <div class="card">
      <h3 class="section-sub">${esc(plan.name || plan.plan_name || 'SIM plan')}</h3>
      ${plan.provider ? `<p><span class="badge">Provider</span> ${esc(plan.provider)}</p>` : ''}
      ${plan.data ? `<p><span class="badge">Data</span> ${esc(plan.data)}</p>` : ''}
      ${plan.price || plan.cost ? `<p><span class="badge">Price</span> ${esc(plan.price || plan.cost)}</p>` : ''}
      ${plan.notes ? `<p class="note">${esc(plan.notes)}</p>` : ''}
    </div>`).join('');
}

// ---------------------------------------------------------------------------
// Inline CSS
// ---------------------------------------------------------------------------

const INLINE_CSS = `
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

  body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto,
                 Helvetica, Arial, sans-serif;
    font-size: 15px;
    line-height: 1.6;
    color: #1a1a2e;
    background: #f4f6f8;
    padding: 24px 16px 48px;
  }

  .page-header {
    background: #0d9488;
    color: #fff;
    padding: 28px 32px;
    border-radius: 10px;
    margin-bottom: 32px;
  }

  .page-header h1 {
    font-size: 1.8rem;
    font-weight: 700;
    letter-spacing: -0.3px;
  }

  .page-header .meta {
    margin-top: 6px;
    font-size: 0.9rem;
    opacity: 0.85;
  }

  .toc {
    background: #fff;
    border: 1px solid #e2e8f0;
    border-radius: 8px;
    padding: 18px 24px;
    margin-bottom: 32px;
  }

  .toc h2 { font-size: 1rem; margin-bottom: 10px; color: #0d9488; }

  .toc ul { list-style: none; display: flex; flex-wrap: wrap; gap: 8px; }

  .toc a {
    color: #0d9488;
    text-decoration: none;
    background: #f0fdfa;
    border: 1px solid #99f6e4;
    border-radius: 4px;
    padding: 3px 10px;
    font-size: 0.85rem;
  }

  .toc a:hover { background: #ccfbf1; }

  section { margin-bottom: 40px; }

  section > h2 {
    font-size: 1.2rem;
    font-weight: 700;
    color: #0d9488;
    border-bottom: 2px solid #0d9488;
    padding-bottom: 6px;
    margin-bottom: 16px;
  }

  .card {
    background: #fff;
    border: 1px solid #e2e8f0;
    border-radius: 8px;
    padding: 18px 20px;
    margin-bottom: 14px;
  }

  .section-sub {
    font-size: 1rem;
    font-weight: 600;
    color: #1e293b;
    margin-bottom: 10px;
  }

  .slot-table, .info-table {
    width: 100%;
    border-collapse: collapse;
    font-size: 0.9rem;
  }

  .slot-table td, .info-table td {
    padding: 7px 10px;
    border-bottom: 1px solid #f1f5f9;
    vertical-align: top;
  }

  .slot-table tr:last-child td, .info-table tr:last-child td {
    border-bottom: none;
  }

  .time-cell {
    white-space: nowrap;
    color: #64748b;
    width: 90px;
  }

  .label-cell {
    white-space: nowrap;
    width: 180px;
  }

  .tip-list {
    list-style: disc;
    padding-left: 20px;
  }

  .tip-list li { margin-bottom: 6px; }

  .badge {
    display: inline-block;
    background: #f0fdfa;
    color: #0d9488;
    border: 1px solid #99f6e4;
    border-radius: 3px;
    font-size: 0.75rem;
    padding: 1px 6px;
    margin-right: 6px;
    font-weight: 600;
    vertical-align: baseline;
  }

  .note { color: #64748b; font-size: 0.875rem; margin-top: 4px; }

  .empty { color: #94a3b8; font-style: italic; padding: 8px 0; }

  .emergency-card { border-left: 4px solid #ef4444; }

  .footer {
    margin-top: 48px;
    text-align: center;
    font-size: 0.8rem;
    color: #94a3b8;
  }

  @media print {
    body { background: #fff; padding: 0; }
    .page-header { border-radius: 0; }
    .card { break-inside: avoid; }
  }
`;

// ---------------------------------------------------------------------------
// Main export
// ---------------------------------------------------------------------------

/**
 * Generate a complete, self-contained HTML file string for offline use.
 *
 * @param {object} params
 * @param {string} params.planName       - Display name of the travel plan
 * @param {object} params.sections       - Keyed section data from the planner result
 * @param {object} [params.searchData]   - Original search request (origin, destination, dates)
 * @returns {string} Full HTML document as a string
 */
export function generateOfflineHTML({ planName, sections = {}, searchData = {} }) {
  const safeTitle = esc(planName || 'My Travel Plan');
  const origin = esc(searchData.origin || '');
  const destination = esc(searchData.destination || '');
  const departure = esc(searchData.departure_date || searchData.departureDate || '');
  const returnDate = esc(searchData.return_date || searchData.returnDate || '');
  const generatedAt = new Date().toLocaleString();

  const metaParts = [
    origin && destination ? `${origin} &rarr; ${destination}` : '',
    departure ? `Departure: ${departure}` : '',
    returnDate ? `Return: ${returnDate}` : '',
  ].filter(Boolean).join(' &nbsp;&bull;&nbsp; ');

  // Resolve section data defensively
  const itineraryData = sections.itinerary?.data || sections.itinerary || null;
  const emergencyData = sections.emergency_card?.data || sections.emergency_card || null;
  const tipsData = sections.tips?.data || sections.tips || null;
  const transportData = sections.getting_around?.data || sections.getting_around || null;
  const simData = sections.sim?.data || sections.sim || null;

  const hasItinerary = itineraryData && (Array.isArray(itineraryData) ? itineraryData.length > 0 : true);
  const hasEmergency = emergencyData !== null;
  const hasTips = tipsData !== null;
  const hasTransport = transportData !== null;
  const hasSim = simData !== null;

  const tocItems = [
    hasItinerary ? '<li><a href="#itinerary">Itinerary</a></li>' : '',
    hasEmergency ? '<li><a href="#emergency">Emergency Contacts</a></li>' : '',
    hasTips ? '<li><a href="#tips">Travel Tips</a></li>' : '',
    hasTransport ? '<li><a href="#transport">Getting Around</a></li>' : '',
    hasSim ? '<li><a href="#sim">SIM / eSIM</a></li>' : '',
  ].filter(Boolean).join('\n          ');

  const itinerarySection = hasItinerary ? `
    <section id="itinerary">
      <h2>Itinerary</h2>
      ${buildItinerary(itineraryData)}
    </section>` : '';

  const emergencySection = hasEmergency ? `
    <section id="emergency">
      <h2>Emergency Contacts</h2>
      ${buildEmergency(emergencyData)}
    </section>` : '';

  const tipsSection = hasTips ? `
    <section id="tips">
      <h2>Travel Tips</h2>
      ${buildTips(tipsData)}
    </section>` : '';

  const transportSection = hasTransport ? `
    <section id="transport">
      <h2>Getting Around</h2>
      ${buildTransport(Array.isArray(transportData) ? transportData : [transportData])}
    </section>` : '';

  const simSection = hasSim ? `
    <section id="sim">
      <h2>SIM / eSIM Plans</h2>
      ${buildSim(Array.isArray(simData) ? simData : [simData])}
    </section>` : '';

  return `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>${safeTitle} — Offline Travel Plan</title>
  <style>${INLINE_CSS}</style>
</head>
<body>

  <div class="page-header">
    <h1>${safeTitle}</h1>
    ${metaParts ? `<p class="meta">${metaParts}</p>` : ''}
    <p class="meta">Generated: ${esc(generatedAt)}</p>
  </div>

  ${tocItems ? `
  <nav class="toc">
    <h2>Contents</h2>
    <ul>
          ${tocItems}
    </ul>
  </nav>` : ''}

  ${itinerarySection}
  ${emergencySection}
  ${tipsSection}
  ${transportSection}
  ${simSection}

  <footer class="footer">
    <p>This document was generated for offline use by the Travel Planner app.</p>
    <p>Print-friendly &mdash; use your browser&rsquo;s Print function to save as PDF.</p>
  </footer>

</body>
</html>`;
}
