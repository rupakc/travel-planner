// @vitest-environment jsdom
import { describe, it, expect } from 'vitest'
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import AttributionFooter from './AttributionFooter'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

describe('AttributionFooter', () => {
  it('credits GeoNames, the licence and OurAirports with links', () => {
    const container = document.createElement('div')
    const root = createRoot(container)
    act(() => root.render(<AttributionFooter />))
    expect(container.textContent).toContain(
      'Place data © GeoNames (CC BY 4.0) · Airport data: OurAirports',
    )
    const hrefs = Object.fromEntries(
      [...container.querySelectorAll('a')].map((a) => [a.textContent, a.getAttribute('href')]),
    )
    expect(hrefs).toEqual({
      GeoNames: 'https://www.geonames.org/',
      'CC BY 4.0': 'https://creativecommons.org/licenses/by/4.0/',
      OurAirports: 'https://ourairports.com/',
    })
    act(() => root.unmount())
  })
})
