// @vitest-environment node
import { describe, it, expect } from 'vitest'
import {
  IMPORT_EXAMPLES, MAX_MUST_INCLUDE,
  detectImportInput, importErrorView, checkImageFile, defaultImportDates,
  previewToDraft, buildImportSearch, linkCoverageSummary, chatImportLink, importLinkFromQuery,
} from './linkImport'

const PREVIEW = {
  source: { kind: 'url', url: 'https://wander.example/lisbon', title: '48 Hours in Lisbon | Wander', site_name: 'Wander' },
  title: '48 hours in Lisbon',
  summary: 'Viewpoints and pastries.',
  destinations: [
    { name: 'Lisbon, Portugal', city: 'Lisbon', country: 'Portugal', airports: ['LIS'], lat: 38.7, lng: -9.1, place_count: 3, nights: 3 },
    { name: 'Porto, Portugal', city: 'Porto', country: 'Portugal', airports: ['OPO'], lat: 41.1, lng: -8.6, place_count: 1, nights: 1 },
  ],
  places: [
    { id: 'p1', name: 'Time Out Market', kind: 'food', city: 'Lisbon', destination: 'Lisbon, Portugal', lat: 38.707, lng: -9.146, approximate: false, verified: true, note: 'Lunch', quote: 'start here' },
    { id: 'p2', name: 'Belém Tower', kind: 'sight', city: 'Lisbon', destination: 'Lisbon, Portugal', lat: 38.7, lng: -9.1, approximate: true, verified: false },
    { id: 'p3', name: 'Pena Palace', kind: 'sight', city: 'Sintra', destination: 'Lisbon, Portugal', lat: 38.8, lng: -9.4, approximate: true, verified: false },
    { id: 'p4', name: 'Livraria Lello', kind: 'shopping', city: 'Porto', destination: 'Porto, Portugal', lat: 41.1, lng: -8.6, approximate: true, verified: false },
  ],
  unresolved: [{ id: 'p5', name: 'Mystery Bar', kind: 'drink', city: 'Xqz', destination: null }],
  suggested_days: 4,
  interests: ['food', 'viewpoints'],
  warnings: [],
}

describe('detectImportInput', () => {
  it.each([
    ['https://blog.example/trip', 'https://blog.example/trip'],
    ['  http://x.example/a?b=1  ', 'http://x.example/a?b=1'],
    ['www.lonelyplanet.com/portugal/lisbon', 'https://www.lonelyplanet.com/portugal/lisbon'],
    ['youtu.be/abc123', 'https://youtu.be/abc123'],
  ])('reads %s as a link', (raw, url) => {
    expect(detectImportInput(raw)).toEqual({ kind: 'url', url })
  })

  it.each(['Belém Tower and LX Factory', 'Lisbon', 'Day 1: Colosseum.\nDay 2: Vatican', 'ftp://x.example/file'])(
    'reads %s as text', (raw) => {
      expect(detectImportInput(raw).kind).toBe('text')
    })

  it('treats blank input as empty', () => {
    expect(detectImportInput('   ').kind).toBe('empty')
  })
})

describe('importErrorView', () => {
  const axiosErr = (status, detail) => ({ response: { status, data: { detail } } })

  it('offers text and screenshots for a blocked source', () => {
    const v = importErrorView(axiosErr(422, { code: 'blocked_source', message: 'Instagram doesn\'t let apps read posts.' }))
    expect(v.code).toBe('blocked_source')
    expect(v.message).toContain('Instagram')
    expect(v.actions).toEqual(['text', 'images'])
  })

  it('suggests text or screenshots for sites that block apps', () => {
    expect(importErrorView(axiosErr(422, { code: 'blocked_by_site', message: 'm' })).actions).toEqual(['text', 'images'])
  })

  it('suggests pasting text for paywalls and empty pages', () => {
    expect(importErrorView(axiosErr(422, { code: 'paywall', message: 'm' })).actions).toEqual(['text', 'images'])
    expect(importErrorView(axiosErr(422, { code: 'no_places', message: 'm' })).actions).toEqual(['text'])
  })

  it('shows the rate-limit detail as-is', () => {
    const v = importErrorView(axiosErr(429, 'Too many requests — please wait 30 seconds and try again.'))
    expect(v.code).toBe('rate_limited')
    expect(v.message).toBe('Too many requests — please wait 30 seconds and try again.')
    expect(v.actions).toEqual([])
  })

  it('shows a too-big upload detail as-is', () => {
    const v = importErrorView(axiosErr(413, 'That upload is too big — use up to 4 screenshots of 5 MB or less.'))
    expect(v.code).toBe('too_large')
    expect(v.message).toContain('too big')
    expect(v.actions).toEqual(['images'])
  })

  it('explains a proxy 413 with no detail', () => {
    expect(importErrorView({ response: { status: 413, data: '<html>' } }).message).toMatch(/too big/)
  })

  it('explains network errors and unknown failures', () => {
    expect(importErrorView({ message: 'Network Error' }).code).toBe('network')
    expect(importErrorView(axiosErr(500, null)).code).toBe('unknown')
    expect(importErrorView(axiosErr(500, null)).actions).toEqual(['retry'])
  })

  it('treats cancellation as silent', () => {
    expect(importErrorView({ code: 'ERR_CANCELED', name: 'CanceledError' })).toBeNull()
  })
})

describe('checkImageFile', () => {
  const file = (name, type, size = 1000) => ({ name, type, size })
  it('accepts the supported image types', () => {
    for (const t of ['image/png', 'image/jpeg', 'image/webp', 'image/gif']) {
      expect(checkImageFile(file('a', t))).toBeNull()
    }
  })
  it('explains HEIC, other files and big images', () => {
    expect(checkImageFile(file('IMG_1.HEIC', ''))).toMatch(/HEIC/)
    expect(checkImageFile(file('a.heif', 'image/heif'))).toMatch(/HEIC/)
    expect(checkImageFile(file('a.pdf', 'application/pdf'))).toMatch(/PNG, JPEG/)
    expect(checkImageFile(file('a.png', 'image/png', 6 * 1024 * 1024))).toMatch(/5 MB/)
  })
})

describe('defaultImportDates', () => {
  it('starts 30 days out and lasts the suggested nights', () => {
    expect(defaultImportDates('2026-11-04', 4)).toEqual({ departure_date: '2026-12-04', return_date: '2026-12-08' })
  })
})

describe('previewToDraft', () => {
  it('leaves hotels and anything past the 25th place unticked', () => {
    const many = Array.from({ length: 28 }, (_, i) => ({ id: `x${i}`, name: `Spot ${i}`, kind: i === 0 ? 'stay' : 'sight', destination: 'Lisbon, Portugal' }))
    const d = previewToDraft({ ...PREVIEW, places: many })
    expect(d.places[0].selected).toBe(false)
    expect(d.places.filter((p) => p.selected)).toHaveLength(MAX_MUST_INCLUDE)
    expect(d.places.at(-1).selected).toBe(false)
  })

  it('selects every placed spot and keeps unresolved ones aside', () => {
    const d = previewToDraft(PREVIEW)
    expect(d.places.map((p) => [p.id, p.selected])).toEqual([['p1', true], ['p2', true], ['p3', true], ['p4', true]])
    expect(d.unresolved.map((p) => p.id)).toEqual(['p5'])
    expect(d.stops.map((s) => [s.city, s.nights, s.included])).toEqual([['Lisbon', 3, true], ['Porto', 1, true]])
  })
})

describe('buildImportSearch', () => {
  const form = {
    origin: 'London', nationality: 'British', interests: ['history'],
    adults: 2, children: 0, seniors: 0, infants: 0, budget_usd: '2000',
    departure_date: '2026-12-04',
  }

  it('builds a multi-city search that must include the chosen places', () => {
    const draft = previewToDraft(PREVIEW)
    draft.places[1].selected = false // drop Belém Tower
    draft.unresolved[0].destination = 'Porto, Portugal' // fixed by the traveller
    const { form: planForm, stops } = buildImportSearch({ form, preview: PREVIEW, draft })
    expect(planForm.destination).toBe('Porto, Portugal')
    expect(stops).toEqual([{ city: 'Lisbon, Portugal', nights: 3 }])
    expect(planForm.departure_date).toBe('2026-12-04')
    expect(planForm.return_date).toBe('2026-12-08')
    expect(planForm.interests).toEqual(['history', 'food', 'viewpoints'])
    expect(planForm.must_include.map((p) => p.name)).toEqual(['Time Out Market', 'Pena Palace', 'Livraria Lello', 'Mystery Bar'])
    const [tom, pena, , mystery] = planForm.must_include
    expect(tom).toEqual({ name: 'Time Out Market', kind: 'food', city: 'Lisbon', town: null, lat: 38.707, lng: -9.146, note: 'Lunch', quote: 'start here', verified: true })
    expect(pena.town).toBe('Sintra')
    expect(pena.lat).toBeNull() // approximate pins never pretend to be exact
    expect(mystery.city).toBe('Porto')
    expect(planForm.import_source).toEqual({ url: 'https://wander.example/lisbon', title: '48 hours in Lisbon' })
  })

  it('drops excluded stops and their places, and caps the list', () => {
    const draft = previewToDraft({
      ...PREVIEW,
      places: Array.from({ length: 30 }, (_, i) => ({ id: `x${i}`, name: `Spot ${i}`, kind: 'sight', city: 'Lisbon', destination: 'Lisbon, Portugal', approximate: true })),
    })
    draft.stops[1].included = false
    const { form: planForm, stops } = buildImportSearch({ form, preview: PREVIEW, draft })
    expect(planForm.destination).toBe('Lisbon, Portugal')
    expect(stops).toEqual([])
    expect(planForm.must_include).toHaveLength(MAX_MUST_INCLUDE)
    expect(planForm.return_date).toBe('2026-12-07')
  })

  it('has no source URL for pasted text', () => {
    const preview = { ...PREVIEW, source: { kind: 'text' } }
    const { form: planForm } = buildImportSearch({ form, preview, draft: previewToDraft(preview) })
    expect(planForm.import_source).toEqual({ url: null, title: '48 hours in Lisbon' })
  })
})

describe('linkCoverageSummary', () => {
  const sd = { must_include: [{ name: 'A' }, { name: 'B' }, { name: 'C' }], import_source: { title: 'T' } }
  const day = (slots, extras) => ({ slots, ...(extras ? { link_extras: extras } : {}) })

  it('counts what the rendered itinerary actually holds, not the server report', () => {
    const itin = {
      days: [day([{ from_link: true, link_place: 'A', link_places: ['A', 'B'] }], [{ name: 'C' }])],
      link_coverage: { scheduled: [], extras: [], missing: ['A', 'B', 'C'] },
    }
    expect(linkCoverageSummary(sd, itin)).toEqual({ total: 3, inItinerary: 3, missing: [], title: 'T', state: 'ready' })
  })
  it('reports places missing from the rendered days (e.g. removed by the traveller)', () => {
    const s = linkCoverageSummary(sd, { days: [day([{ from_link: true, link_place: 'A' }, { activity: 'B tour' }])] })
    expect(s.inItinerary).toBe(1)
    expect(s.missing).toEqual(['B', 'C'])
  })
  it('is pending before the itinerary, failed when it errored, null for ordinary trips', () => {
    expect(linkCoverageSummary(sd, null).state).toBe('pending')
    expect(linkCoverageSummary(sd, null, { failed: true }).state).toBe('failed')
    expect(linkCoverageSummary(sd, { error: 'boom' }).state).toBe('failed')
    expect(linkCoverageSummary({}, null)).toBeNull()
  })
})

describe('deep links', () => {
  it('builds and reads the import link', () => {
    const href = chatImportLink('https://blog.example/a b?x=1&y=2')
    expect(href).toBe('/?import=https%3A%2F%2Fblog.example%2Fa%20b%3Fx%3D1%26y%3D2')
    expect(importLinkFromQuery(href.slice(1))).toBe('https://blog.example/a b?x=1&y=2')
    expect(importLinkFromQuery('?import=javascript%3Aalert(1)')).toBeNull()
    expect(importLinkFromQuery('?other=1')).toBeNull()
  })
})

describe('examples', () => {
  it('has three ready-to-try texts', () => {
    expect(IMPORT_EXAMPLES).toHaveLength(3)
    for (const ex of IMPORT_EXAMPLES) {
      expect(detectImportInput(ex.text).kind).toBe('text')
      expect(ex.label.length).toBeLessThan(30)
    }
  })
})

describe('screenshot sizing', () => {
  it('fits the long edge within 1568 px, keeping the aspect ratio', async () => {
    const { fitWithin, MAX_IMAGE_EDGE } = await import('./linkImport')
    expect(MAX_IMAGE_EDGE).toBe(1568)
    expect(fitWithin(1170, 2532)).toEqual({ width: 725, height: 1568 })
    expect(fitWithin(3000, 1000)).toEqual({ width: 1568, height: 523 })
    expect(fitWithin(800, 600)).toEqual({ width: 800, height: 600 })
  })
})
