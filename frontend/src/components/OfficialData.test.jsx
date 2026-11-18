// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { act } from 'react'
import { createRoot } from 'react-dom/client'

const config = { current: { features: { crawler_data: true } } }
vi.mock('../hooks/useClientConfig', () => ({
  useClientConfig: () => ({ config: config.current, loaded: true }),
  featureOn: (c, name) => c?.features?.[name] === true || c?.features?.[name] === 1,
}))

import { RateSource, EmergencyOfficial, VisaOfficial, HolidayNotice, TypicalFares, SourceLine } from './OfficialData'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

const OGL = 'Contains public sector information licensed under the Open Government Licence v3.0'
const src = (extra = {}) => ({
  source_id: 'govuk-world-orgs', name: 'GOV.UK worldwide organisations',
  url: 'https://www.gov.uk/world/japan', as_of: '2026-11-01',
  licence: 'open', attribution: OGL, licence_url: null, conflict: false, ...extra,
})

describe('OfficialData', () => {
  let container, root
  const render = (el) => act(() => root.render(el))

  beforeEach(() => {
    config.current = { features: { crawler_data: true } }
    container = document.createElement('div')
    document.body.appendChild(container)
    root = createRoot(container)
  })
  afterEach(() => {
    act(() => root.unmount())
    container.remove()
  })

  it('shows nothing when the backend does not report features.crawler_data', () => {
    config.current = { features: {} }
    render(<>
      <RateSource rate={{ rate: 1, rate_source: src() }} />
      <VisaOfficial entries={[{ country: 'Japan', rules: [{ visa_type: 'visa_free', source: src() }] }]} />
      <HolidayNotice holidays={[{ name: 'New Year', start_date: '2027-01-01', end_date: '2027-01-01', nationwide: true, source: src() }]} />
    </>)
    expect(container.innerHTML).toBe('')
  })

  it('shows nothing for sections without crawler data (older backend)', () => {
    render(<>
      <RateSource rate={{ rate: 150 }} />
      <EmergencyOfficial card={{ emergency_numbers: { police: '110' } }} />
      <VisaOfficial entries={undefined} />
      <HolidayNotice holidays={[]} />
      <TypicalFares fares={null} />
    </>)
    expect(container.innerHTML).toBe('')
  })

  it('a source line names the source, links it and shows the date and attribution', () => {
    render(<SourceLine source={src()} />)
    const a = container.querySelector('a[data-tid="results.official.source"]')
    expect(a.getAttribute('href')).toBe('https://www.gov.uk/world/japan')
    expect(a.textContent).toContain('Source: GOV.UK worldwide organisations')
    expect(container.textContent).toContain('as of')
    expect(container.textContent).toContain(OGL)
  })

  it('never links a non-http source url', () => {
    render(<SourceLine source={src({ url: 'javascript:alert(1)' })} />)
    expect(container.querySelector('a')).toBeNull()
  })

  it('flags conflicting sources', () => {
    render(<SourceLine source={src({ conflict: true })} />)
    expect(container.textContent).toContain('Sources disagree')
  })

  it('lists the official medical facilities with the list date and its source', () => {
    render(<EmergencyOfficial card={{
      medical_in_city: true,
      medical_facilities: [{ name: 'Tokyo Medical and Surgical Clinic', city: 'Tokyo', phone: '+81 3 3436 3028', list_updated: '2024-05-02', source: src({ source_id: 'govuk-medical-lists', name: 'FCDO medical list' }) }],
    }} />)
    expect(container.textContent).toContain('Medical facilities (official list)')
    expect(container.textContent).toContain('+81 3 3436 3028')
    expect(container.textContent).toContain('List updated')
    expect(container.textContent).toContain('Source: FCDO medical list')
  })

  it('keeps share-alike reference numbers apart, with their attribution', () => {
    render(<EmergencyOfficial card={{
      official_numbers: { numbers: { police: '110', ambulance: '119' }, source: src({ name: 'English Wikipedia', licence: 'share_alike', attribution: 'Wikipedia contributors' }) },
    }} />)
    expect(container.textContent).toContain('Emergency numbers (reference)')
    expect(container.textContent).toContain('Police: 110')
    expect(container.textContent).toContain('Wikipedia contributors')
  })

  it('labels the Wikipedia visa table as a cross-check, never as the answer', () => {
    render(<VisaOfficial entries={[{
      country: 'Japan',
      rules: [{ visa_type: 'visa_free', max_stay_days: 90, application_url: 'https://www.mofa.go.jp/', source: src({ name: 'FCDO travel advice' }) }],
      advisories: [{ issuer: 'FCDO', level_label: 'See our advice', source: src({ name: 'FCDO travel advice' }) }],
      cross_check: { requirement: 'visa_required', agrees: false, source: src({ name: 'English Wikipedia', licence: 'share_alike', attribution: 'Wikipedia contributors' }) },
    }]} />)
    expect(container.textContent).toContain('Official entry information')
    expect(container.textContent).toContain('VISA FREE')
    expect(container.textContent).toContain('Cross-check (Wikipedia, not an official source)')
    expect(container.textContent).toContain('Differs from the answer above')
    expect(container.querySelector('a[data-tid="results.official.visa-apply"]').getAttribute('href')).toBe('https://www.mofa.go.jp/')
  })

  it('shows holidays with their source', () => {
    render(<HolidayNotice holidays={[
      { name: "New Year's Day", start_date: '2027-01-01', end_date: '2027-01-01', nationwide: true, source: src({ name: 'OpenHolidays API', licence: 'share_alike', attribution: 'OpenHolidays API, CC BY-SA 4.0' }) },
    ]} />)
    expect(container.textContent).toContain('Public holidays during your trip')
    expect(container.textContent).toContain("New Year's Day")
    expect(container.textContent).toContain('OpenHolidays API, CC BY-SA 4.0')
  })

  it('calls a cached fare a cached fare', () => {
    render(<TypicalFares fares={{ price: 612, currency: 'GBP', month: '2026-12', source: src({ name: 'Travelpayouts' }) }} />)
    expect(container.textContent).toContain('not a live price')
    expect(container.textContent).toContain('612 GBP')
  })

  it('shows the published rate source under a rate', () => {
    render(<RateSource rate={{ rate: 161.5, rate_source: src({ name: 'European Central Bank reference rates', via: 'EUR' }) }} />)
    expect(container.textContent).toContain('European Central Bank reference rates')
    expect(container.textContent).toContain('via EUR')
  })
})
