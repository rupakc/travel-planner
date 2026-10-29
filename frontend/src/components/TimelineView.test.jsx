// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach } from 'vitest'
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import TimelineView from './TimelineView'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

describe('TimelineView', () => {
  let container, root
  beforeEach(() => {
    container = document.createElement('div')
    document.body.appendChild(container)
    root = createRoot(container)
  })
  afterEach(() => {
    act(() => root.unmount())
    container.remove()
  })

  it('shows each activity\'s estimated times', () => {
    const itineraryData = {
      days: [{
        day_number: 1, date: '2027-05-01', slots: [
          { key: '1-morning', time_of_day: 'morning', activity: 'Castle', duration_hours: 2 },
          { key: '1-evening', time_of_day: 'evening', activity: 'Fado' },
        ],
      }],
    }
    act(() => root.render(<TimelineView itineraryData={itineraryData} />))
    const times = [...container.querySelectorAll('[data-slot-time]')].map((n) => n.textContent)
    expect(times).toEqual(['09:00–11:00', '18:30–21:00'])
  })
})
