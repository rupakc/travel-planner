// @vitest-environment node
import { describe, it, expect } from 'vitest'
import { describeAssistantForApi, buildApiHistory } from './chatHistory'

describe('describeAssistantForApi', () => {
  it('returns plain text content unchanged', () => {
    expect(describeAssistantForApi({ role: 'assistant', content: 'Hello!' })).toBe('Hello!')
  })

  it('synthesizes text for an itinerary-only turn', () => {
    const msg = {
      role: 'assistant',
      content: '',
      comprehensiveItinerary: {
        destination: 'Tokyo, Japan',
        days: [
          { day_number: 1, slots: [{ activity: 'Senso-ji Temple' }, { activity: 'Ramen tour' }] },
          { day_number: 2, slots: [{ activity: 'TeamLab Planets' }] },
        ],
      },
    }
    const text = describeAssistantForApi(msg)
    expect(text).toContain('2-day itinerary')
    expect(text).toContain('Tokyo, Japan')
    expect(text).toContain('Senso-ji Temple')
  })

  it('synthesizes text for a sections-only turn', () => {
    const msg = { role: 'assistant', content: '', sections: { flights: {}, hotels: {} } }
    const text = describeAssistantForApi(msg)
    expect(text).toContain('flights')
    expect(text).toContain('hotels')
  })

  it('includes the trip route when present', () => {
    const msg = {
      role: 'assistant',
      content: '',
      tripMap: { cities: [{ city: 'Paris' }, { city: 'Rome' }], departure_date: '2026-09-01', return_date: '2026-09-10' },
    }
    const text = describeAssistantForApi(msg)
    expect(text).toContain('Paris → Rome')
    expect(text).toContain('2026-09-01')
  })
})

describe('buildApiHistory', () => {
  it('drops empty assistant turns with no structured data', () => {
    const history = buildApiHistory([
      { role: 'user', content: 'plan a trip to Tokyo' },
      { role: 'assistant', content: '' }, // failed/empty turn
      { role: 'user', content: 'what about the food?' },
    ])
    expect(history).toEqual([
      { role: 'user', content: 'plan a trip to Tokyo' },
      { role: 'user', content: 'what about the food?' },
    ])
  })

  it('keeps full conversation context including synthesized planning turns', () => {
    const history = buildApiHistory([
      { role: 'user', content: 'plan 3 days in Tokyo' },
      { role: 'assistant', content: '', comprehensiveItinerary: { days: [{ day_number: 1, slots: [] }] } },
      { role: 'user', content: 'swap day 1' },
    ])
    expect(history).toHaveLength(3)
    expect(history[1].role).toBe('assistant')
    expect(history[1].content).toContain('itinerary')
  })
})
