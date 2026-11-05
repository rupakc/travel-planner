// @vitest-environment jsdom
// The search form stores the destination as an airport code ("LIS"). Watch
// buttons name the city ("Lisbon") in the spec they send and in the dialog.
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { act, useState } from 'react'
import { createRoot } from 'react-dom/client'
import { MemoryRouter } from 'react-router-dom'

const auth = { token: 'tok' }
vi.mock('../../context/AuthContext', () => ({ useAuth: () => auth, useOptionalAuth: () => auth }))
vi.mock('../../context/AlertsContext', () => ({
  useAlerts: () => ({ caps: { fareWatch: true } }),
  usePriceWatchFor: () => useState(null),
}))
const CITIES = { LIS: 'Lisbon', CDG: 'Paris', OPO: 'Porto', FAO: 'Faro' }
vi.mock('../../services/api', () => ({ airportCity: vi.fn(async (code) => CITIES[code] || null) }))
let dialogProps = null
vi.mock('./PriceWatchDialog', () => ({ default: (p) => { dialogProps = p; return null } }))

import * as api from '../../services/api'
import WatchHotelButton from './WatchHotelButton'
import WatchActivityButton from './WatchActivityButton'
import WatchTripButton from './WatchTripButton'
import { ActivityTripContext } from './activityTripContext'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

const DATES = { departure_date: '2099-12-10', return_date: '2099-12-14', num_travelers: 2 }
const button = (text) => [...document.body.querySelectorAll('button')].find(b => b.textContent.includes(text))

let container, root
beforeEach(() => {
  dialogProps = null
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
})
afterEach(() => {
  act(() => root.unmount())
  container.remove()
})
const render = async (el) => {
  await act(async () => root.render(<MemoryRouter>{el}</MemoryRouter>))
  await act(async () => {}) // the airport lookup settles
}
const openDialog = async () => { await act(async () => button('Watch').click()) }

describe('watch buttons name the city, not the airport code', () => {
  it('hotel: an airport-code destination becomes the city in the spec and dialog', async () => {
    await render(<WatchHotelButton hotel={{ name: 'Memmo Alfama Hotel' }} searchData={{ destination: 'LIS', ...DATES }} />)
    await openDialog()
    expect(dialogProps.spec.city).toBe('Lisbon')
    expect(JSON.stringify(dialogProps.preview)).not.toMatch(/\bLIS\b/)
    expect(api.airportCity).toHaveBeenCalledWith('LIS')
  })

  it('hotel: a card that names its city still matches a code destination', async () => {
    await render(<WatchHotelButton hotel={{ name: 'Pestana Porto', city: 'Porto' }} searchData={{ destination: 'OPO', ...DATES }} />)
    await openDialog()
    expect(dialogProps.spec.city).toBe('Porto')
  })

  it('hotel: a real city name passes through without a lookup', async () => {
    api.airportCity.mockClear()
    await render(<WatchHotelButton hotel={{ name: 'Lumen Hotel' }} searchData={{ destination: 'Lisbon, Portugal', ...DATES }} />)
    await openDialog()
    expect(dialogProps.spec.city).toBe('Lisbon, Portugal')
    expect(api.airportCity).not.toHaveBeenCalled()
  })

  it('activity: the trip destination code becomes the city', async () => {
    await render(
      <ActivityTripContext.Provider value={{ searchData: { destination: 'LIS', num_travelers: 2 }, itinerary: null }}>
        <WatchActivityButton activity={{ name: 'Belém walking tour', price_usd: 30 }} />
      </ActivityTripContext.Provider>,
    )
    await openDialog()
    expect(dialogProps.spec.city).toBe('Lisbon')
  })

  it('activity: on a multi-city trip each activity keeps its own leg city', async () => {
    const trip = { searchData: { destination: 'FAO', destinations: ['CDG', 'FAO'], num_travelers: 1 }, itinerary: null }
    await render(
      <ActivityTripContext.Provider value={trip}>
        <WatchActivityButton activity={{ name: 'Louvre tour', city: 'CDG' }} />
      </ActivityTripContext.Provider>,
    )
    await openDialog()
    expect(dialogProps.spec.city).toBe('Paris')
  })

  it('activity: on a multi-city trip an activity without a city is not guessed', async () => {
    const trip = { searchData: { destination: 'FAO', destinations: ['CDG', 'FAO'], num_travelers: 1 }, itinerary: null }
    await render(
      <ActivityTripContext.Provider value={trip}>
        <WatchActivityButton activity={{ name: 'Mystery tour' }} />
      </ActivityTripContext.Provider>,
    )
    expect(button('Watch')).toBeUndefined()
  })

  it('trip: the dialog subtitle names the city', async () => {
    const plan = { id: 3, name: 'Escape', search_data: { origin: 'BER', destination: 'LIS', ...DATES }, selections: { sim: { price_usd: 13 } } }
    await render(<WatchTripButton plan={plan} />)
    await openDialog()
    expect(dialogProps.preview.subtitle).toMatch(/^Lisbon · /)
  })
})
