// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import PlanExport from './PlanExport'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

vi.mock('../utils/analytics', () => ({ track: () => {} }))

const searchData = { origin: 'New York', destination: 'Tokyo', departure_date: '2027-04-01', return_date: '2027-04-04' }
const selections = { hotel: { name: 'Park Hyatt Tokyo', total_price_usd: 1860 } }

// jsdom's Blob has no .text()
const readBlob = (blob) => new Promise((resolve) => {
  const reader = new FileReader()
  reader.onload = () => resolve(reader.result)
  reader.readAsText(blob)
})

describe('PlanExport', () => {
  let container, root, blobs

  const render = (props = {}) => act(() => root.render(
    <PlanExport planName="Tokyo Trip" searchData={searchData} selections={selections} source="results" {...props} />,
  ))
  const button = (label) => [...container.querySelectorAll('button')].find((b) => b.textContent.includes(label))

  beforeEach(() => {
    blobs = []
    URL.createObjectURL = vi.fn((blob) => { blobs.push(blob); return `blob:test/${blobs.length}` })
    URL.revokeObjectURL = vi.fn()
    container = document.createElement('div')
    document.body.appendChild(container)
    root = createRoot(container)
  })

  afterEach(() => {
    act(() => root.unmount())
    container.remove()
    vi.restoreAllMocks()
  })

  it('renders nothing for an empty plan', () => {
    render({ selections: {} })
    expect(container.innerHTML).toBe('')
  })

  it('downloads an .ics file named after the plan', async () => {
    const clicks = []
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function () { clicks.push(this.download) })
    render()
    act(() => button('Add to calendar').click())
    expect(clicks).toEqual(['tokyo-trip.ics'])
    expect(blobs[0].type).toBe('text/calendar;charset=utf-8')
    expect(await readBlob(blobs[0])).toContain('SUMMARY:🏨 Park Hyatt Tokyo')
  })

  it('keys calendar events to the saved plan', async () => {
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
    render({ planId: 42 })
    act(() => button('Add to calendar').click())
    expect(await readBlob(blobs[0])).toContain('UID:plan-42-hotel@')
  })

  it('opens the printable page in a new tab and cuts its link back to the app window', async () => {
    const tab = { opener: window }
    const open = vi.spyOn(window, 'open').mockReturnValue(tab)
    render()
    act(() => button('Print / PDF').click())
    expect(open).toHaveBeenCalledWith('blob:test/1', '_blank')
    expect(tab.opener).toBeNull()
    expect(await readBlob(blobs[0])).toContain('<title>Tokyo Trip</title>')
    expect(container.querySelector('[role=status]')).toBeNull()
  })

  it('tells the user when the browser blocks the new tab', () => {
    vi.spyOn(window, 'open').mockReturnValue(null)
    render()
    act(() => button('Print / PDF').click())
    expect(container.querySelector('[role=status]').textContent).toMatch(/blocked/i)
  })
})
