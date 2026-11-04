// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { act } from 'react'
import { createRoot } from 'react-dom/client'

vi.mock('../components/TripMap', () => ({ default: () => null }))
vi.mock('../utils/analytics', () => ({ track: vi.fn() }))

import { ActivitiesSection } from './ResultsPage'
import ItinerarySection from '../components/ItinerarySection'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

describe('"From your link" in results', () => {
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

  it('tags imported activities and hides internal source/match labels', () => {
    act(() => root.render(
      <ActivitiesSection
        data={{ results: [
          { name: 'Time Out Market', category: 'food', from_link: true, source: 'your_link', similarity_score: 1, link_quote: 'start here', verification_note: 'Located on Google Maps' },
          { name: 'Oceanário', category: 'nature', source: 'tripadvisor', similarity_score: 0.8 },
        ] }}
        selections={{ activities: [] }} onSelect={() => {}} />,
    ))
    const cards = container.querySelectorAll('[data-activity-card]')
    expect(cards[0].textContent).toContain('From your link')
    expect(cards[0].textContent).not.toContain('your_link')
    expect(cards[0].textContent).not.toContain('100% match')
    expect(cards[1].textContent).not.toContain('From your link')
    act(() => [...cards[0].querySelectorAll('button')].find((b) => b.textContent.includes('From your link')).click())
    expect(cards[0].textContent).toContain('“start here”')
    expect(cards[0].textContent).toContain('Located on Google Maps')
  })

  it('tags itinerary rows and lists extras that did not get a slot', () => {
    const data = {
      days: [{
        day_number: 1, date: '2026-12-01',
        slots: [
          { time_of_day: 'morning', activity: 'Belém Tower', from_link: true, link_place: 'Belém Tower', link_quote: 'go early' },
          { time_of_day: 'afternoon', activity: 'Lunch' },
        ],
        link_extras: [{ name: 'Pena Palace', note: 'Fairy-tale palace' }],
      }],
    }
    act(() => root.render(
      <ItinerarySection data={data} selections={{ itinerary_slots: [], itinerary_notes: {} }}
        onNoteChange={() => {}} onSlotEdit={() => {}} onSlotPlan={() => {}} />,
    ))
    const rows = container.querySelectorAll('[data-slot-key]')
    expect(rows[0].textContent).toContain('From your link')
    expect(rows[1].textContent).not.toContain('From your link')
    expect(container.querySelector('[data-link-extras]').textContent).toContain('Pena Palace')
  })
})
