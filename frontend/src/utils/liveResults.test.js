// @vitest-environment node
import { describe, it, expect } from 'vitest'
import {
  NEARBY_SECTIONS, browserLanguage, placeLabel, geoErrorMessage, googleSearchUrl, liveErrorMessage, nearbySections, roundCoord,
  safeHttpUrl, usableSources,
} from './liveResults'

const httpErr = (status, detail) => ({ response: { status, data: { detail } } })

describe('nearbySections', () => {
  it('always returns the four sections in order, filling gaps with empty ones', () => {
    const out = nearbySections({
      sections: [
        { id: 'eat', title: 'Places to eat', items: [{ name: 'Time Out Market' }, { summary: 'no name' }] },
        { id: 'see', title: 'Places to see', items: [{ name: 'Belém Tower' }] },
      ],
    })
    expect(out.map(s => s.id)).toEqual(NEARBY_SECTIONS.map(s => s.id))
    expect(out[0].items.map(i => i.name)).toEqual(['Belém Tower'])
    expect(out[1].items.map(i => i.name)).toEqual(['Time Out Market']) // nameless item dropped
    expect(out[2]).toMatchObject({ title: 'Places to shop', items: [] })
    expect(out[3].empty).toMatch(/stay/)
  })

  it('copes with a missing or malformed body', () => {
    expect(nearbySections(null).every(s => s.items.length === 0)).toBe(true)
    expect(nearbySections({ sections: 'x' })).toHaveLength(4)
  })
})

describe('links', () => {
  it('keeps only http(s) URLs', () => {
    expect(safeHttpUrl('https://maps.google.com/?cid=1')).toBe('https://maps.google.com/?cid=1')
    expect(safeHttpUrl('javascript:alert(1)')).toBeNull()
    expect(safeHttpUrl('not a url')).toBeNull()
    expect(safeHttpUrl(null)).toBeNull()
  })

  it('keeps each source’s original index so quotes can cite it', () => {
    const out = usableSources([{ title: 'Bad', uri: 'ftp://x' }, { title: 'Booking', uri: 'https://booking.example/a' }])
    expect(out).toEqual([{ index: 1, title: 'Booking', uri: 'https://booking.example/a' }])
  })

  it('builds Google Search links', () => {
    expect(googleSearchUrl('memmo alfama & price')).toBe('https://www.google.com/search?q=memmo%20alfama%20%26%20price')
  })

  it('rounds coordinates to ~100 m', () => {
    expect(roundCoord(38.722345)).toBe(38.722)
    expect(roundCoord(-9.13961)).toBe(-9.14)
  })
})

describe('liveErrorMessage', () => {
  it('shows the 429 string detail as-is', () => {
    expect(liveErrorMessage(httpErr(429, 'Too many requests — please wait 30 seconds.'), 'nearby'))
      .toMatchObject({ code: 'rate_limited', text: 'Too many requests — please wait 30 seconds.' })
  })

  it('maps the AI pause codes to friendly copy', () => {
    expect(liveErrorMessage(httpErr(503, { code: 'ai_limit', message: 'AI limit reached for this month — try again on the 1st.' })))
      .toMatchObject({ code: 'ai_limit', retry: false, text: 'AI limit reached for this month — try again on the 1st.' })
    expect(liveErrorMessage(httpErr(503, { code: 'ai_billing' })).text).toMatch(/unavailable right now/)
  })

  it('never shows the developer message for grounding_unavailable', () => {
    const detail = { code: 'grounding_unavailable', message: 'Live web and map results need the Gemini provider.' }
    expect(liveErrorMessage(httpErr(503, detail), 'nearby').text).toBe('Live map results aren’t available on this server right now.')
    expect(liveErrorMessage(httpErr(503, detail), 'live').text).toBe('Live web search isn’t available on this server right now.')
  })

  it('maps 404 per feature', () => {
    expect(liveErrorMessage(httpErr(404, { code: 'no_place', message: 'We don\'t know a town or city near you yet.' }), 'nearby'))
      .toMatchObject({ code: 'no_place', retry: false, text: 'We don\'t know a town or city near you yet.' })
    expect(liveErrorMessage(httpErr(404, 'Watch not found'), 'live'))
      .toMatchObject({ code: 'not_found', retry: false })
  })

  it('maps 409 watch_expired without a retry', () => {
    expect(liveErrorMessage(httpErr(409, { code: 'watch_expired', message: 'The watch has expired.' }), 'live'))
      .toEqual({ code: 'watch_expired', retry: false, text: 'This trip’s dates have passed, so there’s nothing live to check.' })
  })

  it('maps 502 with or without a message', () => {
    expect(liveErrorMessage(httpErr(502, { code: 'live_check_failed', message: 'No grounded answer.' })))
      .toMatchObject({ code: 'live_check_failed', retry: true, text: 'No grounded answer.' })
    expect(liveErrorMessage(httpErr(502, { code: 'agent_error' }), 'nearby').text).toMatch(/couldn’t find places/)
  })

  it('handles network errors and unknown statuses without raw JSON', () => {
    expect(liveErrorMessage(new Error('Network Error')).code).toBe('network')
    expect(liveErrorMessage(httpErr(500, { weird: true })).text).not.toMatch(/\{/)
  })
})

describe('geoErrorMessage', () => {
  it('explains denied, unavailable, timeout and unsupported', () => {
    expect(geoErrorMessage(1).code).toBe('denied')
    expect(geoErrorMessage(1).text).toMatch(/settings/)
    expect(geoErrorMessage(2).code).toBe('unavailable')
    expect(geoErrorMessage(3).code).toBe('timeout')
    expect(geoErrorMessage('unsupported').code).toBe('unsupported')
  })
})

describe('placeLabel', () => {
  it('drops a region or country that repeats an earlier part (case and accents ignored)', () => {
    expect(placeLabel({ name: 'Lisbon', region: 'Lisbon', country: 'Portugal' })).toBe('Lisbon, Portugal')
    expect(placeLabel({ name: 'Bogotá', region: 'BOGOTA', country: 'Colombia' })).toBe('Bogotá, Colombia')
    expect(placeLabel({ name: 'Singapore', region: null, country: 'Singapore' })).toBe('Singapore')
    expect(placeLabel({ name: 'Portland', region: 'Maine', country: 'United States' })).toBe('Portland, Maine, United States')
    expect(placeLabel(null)).toBe('')
  })
})

describe('browserLanguage', () => {
  it('passes a BCP-47 tag through and falls back to en', () => {
    expect(browserLanguage({ language: 'pt-PT' })).toBe('pt-PT')
    expect(browserLanguage({ language: 'zh_Hant_TW' })).toBe('zh_Hant_TW')
    expect(browserLanguage({ language: 'x' })).toBe('en')
    expect(browserLanguage({ language: 'en US;bad' })).toBe('en')
    expect(browserLanguage({})).toBe('en')
    expect(browserLanguage(null)).toBe('en')
  })
})
