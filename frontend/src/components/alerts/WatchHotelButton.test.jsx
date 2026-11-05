// @vitest-environment jsdom
// The button's side of the dialog contract: a watched suggestion is another
// hotel, so the card's own hotel stays unwatched.
import { describe, it, expect, vi } from 'vitest'
import { act, useState } from 'react'
import { createRoot } from 'react-dom/client'
import { MemoryRouter } from 'react-router-dom'

const auth = { token: 'tok' }
vi.mock('../../context/AuthContext', () => ({ useAuth: () => auth, useOptionalAuth: () => auth }))
vi.mock('../../context/AlertsContext', () => ({
  useAlerts: () => ({ caps: { fareWatch: true } }),
  usePriceWatchFor: () => useState(null),
}))
let dialogProps = null
vi.mock('./PriceWatchDialog', () => ({ default: (p) => { dialogProps = p; return null } }))

import WatchHotelButton from './WatchHotelButton'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

const SEARCH = { destination: 'Lisbon', departure_date: '2099-12-10', return_date: '2099-12-14', adults: 2 }
const WATCH = { id: 11, kind: 'hotel', status: 'active', last_price: 398 }
const button = (text) => [...document.body.querySelectorAll('button')].find(b => b.textContent.includes(text))

describe('WatchHotelButton + dialog contract', () => {
  it('marks itself watched only for its own hotel', async () => {
    const container = document.createElement('div')
    document.body.appendChild(container)
    const root = createRoot(container)
    globalThis.IS_REACT_ACT_ENVIRONMENT = true
    await act(async () => root.render(<MemoryRouter><WatchHotelButton hotel={{ name: 'Lumen Hotel' }} searchData={SEARCH} /></MemoryRouter>))
    await act(async () => button('Watch price').click())
    expect(dialogProps.kind).toBe('hotel')
    await act(async () => dialogProps.onWatched({ ...WATCH, id: 12 }, { spec: { property_token: 'x' }, viaSuggestion: true }))
    expect(button('Watch price')).toBeTruthy()
    await act(async () => dialogProps.onWatched(WATCH, { spec: dialogProps.spec, viaSuggestion: false }))
    expect(button('Watching').textContent).toBe('Watching · $398')
    act(() => root.unmount())
  })
})
