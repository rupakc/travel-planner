// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { ChatPlanDrawer } from './ChatPage'
import { EMPTY_SELECTIONS } from '../utils/planHelpers'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

const HOTEL = { name: 'Hotel Sakura', price_per_night_usd: 120, booking_url: 'https://example.com/h', link_verified: true, link_checked: '2026-10-30' }
const ACTIVITY = { name: 'Senso-ji', link_verified: false, link_checked: '2026-10-30' }

const selectionsWithEvidence = () => ({ ...EMPTY_SELECTIONS, hotel: { ...HOTEL }, activities: [{ ...ACTIVITY }] })

describe('ChatPlanDrawer saves', () => {
  let container, root, fetchMock
  beforeEach(() => {
    container = document.createElement('div')
    document.body.appendChild(container)
    root = createRoot(container)
    fetchMock = vi.fn(async () => ({ ok: true, json: async () => [] }))
    vi.stubGlobal('fetch', fetchMock)
  })
  afterEach(() => {
    act(() => root.unmount())
    container.remove()
    vi.unstubAllGlobals()
  })

  const render = (props) => act(() => root.render(
    <ChatPlanDrawer
      isOpen={false}
      onClose={() => {}}
      searchContext={{}}
      planName="Tokyo"
      onPlanNameChange={() => {}}
      onRemoveSelection={() => {}}
      token="tok"
      loadedPlanId={null}
      onLoadPlan={() => {}}
      onClearLoadedPlan={() => {}}
      onClearSelections={() => {}}
      {...props}
    />,
  ))
  const button = (re) => [...container.querySelectorAll('button')].find((b) => re.test(b.textContent))
  const savedBody = () => {
    const call = fetchMock.mock.calls.find(([, init]) => init && (init.method === 'POST' || init.method === 'PUT'))
    return JSON.parse(call[1].body)
  }
  const expectNoEvidence = (sel) => {
    expect(sel.hotel).toEqual({ name: 'Hotel Sakura', price_per_night_usd: 120, booking_url: 'https://example.com/h' })
    expect(sel.activities).toEqual([{ name: 'Senso-ji' }])
  }

  it('Save Plan sends selections without link evidence and leaves state untouched', async () => {
    const selections = selectionsWithEvidence()
    render({ selections })
    await act(async () => { button(/Save Plan/).click() })
    expectNoEvidence(savedBody().selections)
    expect(selections.hotel.link_verified).toBe(true)
    expect(selections.activities[0].link_checked).toBe('2026-10-30')
  })

  it('Save & Send (update path) sends selections without link evidence', async () => {
    const selections = selectionsWithEvidence()
    render({ selections, loadedPlanId: 7 })
    await act(async () => { button(/Save & Send/).click() })
    const call = fetchMock.mock.calls.find(([, init]) => init?.method === 'PUT')
    expect(call[0]).toBe('/api/plans/7')
    expectNoEvidence(savedBody().selections)
    expect(selections.hotel.link_verified).toBe(true)
  })
})
