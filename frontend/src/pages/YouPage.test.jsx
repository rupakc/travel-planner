// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { MemoryRouter, Routes, Route } from 'react-router-dom'

const journey = vi.hoisted(() => ({ enabled: true }))
vi.mock('../hooks/useJourney', () => ({ useJourney: () => ({ enabled: journey.enabled }) }))
vi.mock('./AccountPage', () => ({ default: () => <div data-tid="account.page" /> }))

import { initI18n } from '../i18n/index'
import YouPage from './YouPage'

globalThis.IS_REACT_ACT_ENVIRONMENT = true
let container, root
const tid = (id) => container.querySelector(`[data-tid="${id}"]`)
const mount = () => act(async () => {
  root.render(
    <MemoryRouter initialEntries={['/you']}>
      <Routes>
        <Route path="/you" element={<YouPage />} />
        <Route path="/trips" element={<div data-tid="trips.page" />} />
      </Routes>
    </MemoryRouter>,
  )
})

beforeEach(async () => {
  await initI18n({ lng: 'en' })
  journey.enabled = true
  container = document.createElement('div'); document.body.appendChild(container); root = createRoot(container)
})
afterEach(() => { act(() => root.unmount()); container.remove() })

describe('YouPage', () => {
  it('shows the account sections then the links', async () => {
    await mount()
    expect(tid('account.page')).not.toBeNull()
    expect(tid('you.preferences').getAttribute('href')).toBe('/preferences')
    expect(tid('you.alerts').getAttribute('href')).toBe('/alerts')
  })

  it('"Show me around" replays the tour and opens Trips', async () => {
    const heard = vi.fn()
    window.addEventListener('voyager:replay-journey-tour', heard)
    await mount()
    await act(async () => { tid('you.tour').click() })
    window.removeEventListener('voyager:replay-journey-tour', heard)
    expect(heard).toHaveBeenCalledTimes(1)
    expect(tid('trips.page')).not.toBeNull()
  })

  it('renders nothing when the journey is off', async () => {
    journey.enabled = false
    await mount()
    expect(container.innerHTML).toBe('')
  })
})
