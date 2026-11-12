// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { act } from 'react'
import { createRoot } from 'react-dom/client'

const journey = vi.hoisted(() => ({ value: { enabled: true, tripsApi: true } }))
const putSnapshot = vi.hoisted(() => vi.fn(async () => ({})))
vi.mock('../hooks/useJourney', () => ({ useJourney: () => journey.value }))
vi.mock('../services/tripsApi', () => ({ putSnapshot, notifyTripsChanged: vi.fn() }))
vi.mock('../telemetry/client', () => ({ emit: vi.fn() }))

import { ChatPlanDrawer } from './ChatPage'
import { EMPTY_SELECTIONS } from '../utils/planHelpers'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

const SECTIONS = { forex: { currency: 'JPY', verification: { level: 'verified' } }, visa: { error: 'x' } }

describe('ChatPlanDrawer trips', () => {
  let container, root
  beforeEach(() => {
    putSnapshot.mockClear()
    journey.value = { enabled: true, tripsApi: true }
    container = document.createElement('div')
    document.body.appendChild(container)
    root = createRoot(container)
    vi.stubGlobal('fetch', vi.fn(async (url, init) => ({ ok: true, json: async () => (init?.method === 'POST' ? { id: 9 } : []) })))
  })
  afterEach(() => { act(() => root.unmount()); container.remove(); vi.unstubAllGlobals() })

  const render = (props) => act(() => root.render(
    <ChatPlanDrawer isOpen onClose={() => {}} selections={{ ...EMPTY_SELECTIONS, hotel: { name: 'Hotel Sakura' } }} searchContext={{}} planName="Tokyo"
      onPlanNameChange={() => {}} onRemoveSelection={() => {}} token="tok" loadedPlanId={null}
      onLoadPlan={() => {}} onClearLoadedPlan={() => {}} onClearSelections={() => {}} onOpenTrip={() => {}} {...props} />,
  ))
  const btn = (re) => [...container.querySelectorAll('button')].find((b) => re.test(b.textContent))

  it('save with section results sends the snapshot', async () => {
    render({ sectionResults: SECTIONS })
    await act(async () => { btn(/Save Plan/).click() })
    expect(putSnapshot).toHaveBeenCalledTimes(1)
    const [tok, id, snap] = putSnapshot.mock.calls[0]
    expect([tok, id]).toEqual(['tok', 9])
    expect(snap.forex).toEqual({ currency: 'JPY' })
    expect(snap.visa).toBeNull()
  })

  it('update path sends the snapshot for the loaded plan', async () => {
    render({ sectionResults: SECTIONS, loadedPlanId: 7 })
    await act(async () => { btn(/Save & Send/).click() })
    expect(putSnapshot.mock.calls[0][1]).toBe(7)
  })

  it('save without section results sends none', async () => {
    render({ sectionResults: {} })
    await act(async () => { btn(/Save Plan/).click() })
    expect(putSnapshot).not.toHaveBeenCalled()
  })

  it('Open trip only with the journey on; meter follows the flag', async () => {
    render({ sectionResults: SECTIONS })
    await act(async () => { btn(/Save Plan/).click() })
    expect(container.querySelector('[data-tid="chat.open-trip"]')).toBeTruthy()
    expect(container.querySelector('[data-tid="completeness.meter"]')).toBeTruthy()
    journey.value = { enabled: false, tripsApi: true }
    render({ sectionResults: SECTIONS })
    expect(container.querySelector('[data-tid="chat.open-trip"]')).toBeNull()
    expect(container.querySelector('[data-tid="completeness.meter"]')).toBeNull()
  })
})
