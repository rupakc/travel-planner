// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { act, useState } from 'react'
import { createRoot } from 'react-dom/client'
import { moveSlot, removeSlot, restoreSlot } from '../utils/itineraryLayout'
import ItinerarySection from './ItinerarySection'

vi.mock('../utils/analytics', () => ({ track: vi.fn() }))
vi.mock('./TripMap', () => ({
  default: ({ days }) => (
    <div data-testid="trip-map" data-activities={days.flatMap(d => (d.slots || []).map(s => s.activity)).join('|')} />
  ),
}))

globalThis.IS_REACT_ACT_ENVIRONMENT = true

const MIME = 'application/x-itinerary-slot'

const slot = (time_of_day, activity, cost = 10) => ({
  time_of_day, activity, location: `${activity} St`, duration_hours: 2, notes: '', estimated_cost_usd: cost,
})

const ITIN = {
  days: [
    { day_number: 1, date: '2026-05-01', theme: 'Old town', slots: [slot('morning', 'Cathedral'), slot('afternoon', 'Market', 20), slot('evening', 'Tapas', 30)] },
    { day_number: 2, date: '2026-05-02', theme: 'Gaudí', slots: [slot('morning', 'Sagrada Familia', 40), slot('afternoon', 'Park Guell', 15)] },
  ],
  total_estimated_cost_usd: 115,
}

const MULTI = {
  days: [
    { day_number: 1, city: 'Rome, Italy', slots: [slot('morning', 'Colosseum'), slot('afternoon', 'Forum')] },
    { day_number: 2, city: 'Florence', slots: [slot('morning', 'Uffizi'), slot('afternoon', 'Duomo')] },
  ],
}

function transfer(initial = {}) {
  const store = { ...initial }
  return {
    setData: vi.fn((type, value) => { store[type] = value }),
    getData: (type) => store[type] ?? '',
    get types() { return Object.keys(store) },
    dropEffect: 'none',
    effectAllowed: 'all',
  }
}

function fire(el, type, dataTransfer) {
  const evt = new Event(type, { bubbles: true, cancelable: true })
  Object.defineProperty(evt, 'dataTransfer', { value: dataTransfer })
  act(() => { el.dispatchEvent(evt) })
  return evt
}

// Minimal stand-in for ResultsPage: applies the layout mutators and keeps an undo stack.
function Stateful({ data }) {
  const [layout, setLayout] = useState(null)
  const [history, setHistory] = useState([])
  const push = (next) => { setHistory((h) => [...h, layout]); setLayout(next) }
  return (
    <ItinerarySection
      data={data}
      selections={{ itinerary_layout: layout }}
      onNoteChange={() => {}} onSlotEdit={() => {}} onSlotPlan={() => {}}
      onMoveSlot={(k, d, t) => push(moveSlot(data, layout, k, d, t))}
      onRemoveSlot={(k) => push(removeSlot(data, layout, k))}
      onRestoreSlot={(k) => push(restoreSlot(data, layout, k))}
      onUndoLayout={() => { setLayout(history.at(-1)); setHistory((h) => h.slice(0, -1)) }}
      onResetLayout={() => push(null)}
      canUndo={history.length > 0}
    />
  )
}

const posOfLabel = (label) => {
  const m = label.match(/Day (\d+) · (\w+)/)
  return `${m[1]}-${m[2].toLowerCase()}`
}

describe('ItinerarySection', () => {
  let container, root
  const handlers = () => ({
    onNoteChange: vi.fn(),
    onSlotEdit: vi.fn(),
    onSlotPlan: vi.fn(),
    onMoveSlot: vi.fn(),
    onRemoveSlot: vi.fn(),
    onRestoreSlot: vi.fn(),
    onUndoLayout: vi.fn(),
    onResetLayout: vi.fn(),
  })
  const render = (props) => act(() => root.render(<ItinerarySection data={ITIN} selections={{}} {...props} />))
  const row = (key) => container.querySelector(`[data-slot-key="${key}"]`)
  const free = (pos) => container.querySelector(`[data-free-slot="${pos}"]`)
  const buttons = (scope = container) => [...scope.querySelectorAll('button')]
  const button = (text, scope = document.body) => buttons(scope).find(b => b.textContent.trim() === text)
  const click = (el) => act(() => { el.click() })
  const activities = (dayIndex) => [...container.querySelectorAll('[data-day]')][dayIndex]
    .querySelectorAll('[data-slot-key] [data-activity]')

  beforeEach(() => {
    container = document.createElement('div')
    document.body.appendChild(container)
    root = createRoot(container)
  })
  afterEach(() => {
    act(() => root.unmount())
    container.remove()
    vi.clearAllMocks()
  })

  it('renders the arranged order, costs and map from the layout', () => {
    const layout = moveSlot(ITIN, null, '1-morning', 2, 'afternoon') // swaps with Park Guell
    render({ ...handlers(), selections: { itinerary_layout: layout } })
    expect([...activities(0)].map(n => n.textContent)).toEqual(['Park Guell', 'Market', 'Tapas'])
    expect([...activities(1)].map(n => n.textContent)).toEqual(['Sagrada Familia', 'Cathedral'])
    expect(container.querySelector('[data-testid="trip-map"]').dataset.activities)
      .toBe('Park Guell|Market|Tapas|Sagrada Familia|Cathedral')
    expect(container.textContent).toContain('$65 est.') // day 1: 15 + 20 + 30
    expect(container.textContent).toContain('Est. itinerary cost: $115')
  })

  it('renders exactly as before without a layout and without move callbacks', () => {
    render({ onNoteChange: vi.fn(), onSlotEdit: vi.fn(), onSlotPlan: vi.fn() })
    expect([...activities(1)].map(n => n.textContent)).toEqual(['Sagrada Familia', 'Park Guell'])
    expect(container.querySelector('[draggable="true"]')).toBeNull()
    expect(button('Move')).toBeUndefined()
    expect(container.querySelector('[data-free-slot]')).toBeNull()
    expect(container.querySelector('[aria-live]')).toBeNull()
  })

  it('shows the editing-disabled note and no Move buttons without move callbacks', () => {
    render({ onNoteChange: vi.fn(), onSlotEdit: vi.fn(), onSlotPlan: vi.fn(), editingDisabledReason: 'Editing is off while a saved plan is open. Click New in My Plan to edit this itinerary.' })
    expect(container.textContent).toContain('Editing is off while a saved plan is open. Click New in My Plan to edit this itinerary.')
    expect(button('Move')).toBeUndefined()
  })

  it('makes movable rows draggable with a handle', () => {
    render(handlers())
    const r = row('1-morning')
    expect(r.getAttribute('draggable')).toBe('true')
    const handle = r.querySelector('[data-drag-handle]')
    expect(handle).not.toBeNull()
    expect(handle.getAttribute('aria-hidden')).toBe('true')
  })

  it('drags with the custom MIME type and drops onto another slot', () => {
    const h = handlers()
    render(h)
    const dt = transfer()
    fire(row('1-morning'), 'dragstart', dt)
    expect(dt.setData).toHaveBeenCalledWith(MIME, '1-morning')
    expect(dt.types).not.toContain('application/json')
    const over = fire(row('2-afternoon'), 'dragover', dt)
    expect(over.defaultPrevented).toBe(true)
    expect(row('2-afternoon').className).toContain('ring-2 ring-teal-400 bg-teal-50')
    const drop = fire(row('2-afternoon'), 'drop', dt)
    expect(drop.defaultPrevented).toBe(true)
    expect(h.onMoveSlot).toHaveBeenCalledWith('1-morning', 2, 'afternoon', 'drag')
    expect(container.querySelector('[aria-live="polite"]').textContent)
      .toBe('Moved Cathedral to Day 2 · Afternoon (swapped with Park Guell)')
  })

  it('ignores a drop that only carries application/json', () => {
    const h = handlers()
    render(h)
    const dt = transfer({ 'application/json': '{"name":"plan"}' })
    expect(fire(row('2-afternoon'), 'dragover', dt).defaultPrevented).toBe(false)
    fire(row('2-afternoon'), 'drop', dt)
    expect(h.onMoveSlot).not.toHaveBeenCalled()
  })

  it('does not accept a cross-city drag', () => {
    const h = handlers()
    render({ ...h, data: MULTI })
    const dt = transfer()
    fire(row('1-morning'), 'dragstart', dt)
    expect(fire(row('2-morning'), 'dragover', dt).defaultPrevented).toBe(false)
    expect(row('2-morning').className).not.toContain('ring-teal-400')
    expect(fire(row('1-afternoon'), 'dragover', dt).defaultPrevented).toBe(true)
    fire(row('2-morning'), 'drop', dt)
    expect(h.onMoveSlot).not.toHaveBeenCalled()
  })

  it('Move menu lists exactly the valid targets and moves via the menu', () => {
    const h = handlers()
    render({ ...h, data: MULTI })
    const move = button('Move', row('1-morning'))
    expect(move.getAttribute('aria-haspopup')).toBe('menu')
    expect(move.getAttribute('aria-expanded')).toBe('false')
    click(move)
    expect(move.getAttribute('aria-expanded')).toBe('true')
    const menu = document.querySelector('[role="menu"]')
    const items = [...menu.querySelectorAll('[role="menuitem"]')]
    expect(items.map(b => b.textContent)).toEqual([
      'Remove from day',
      'Afternoon (swap with Forum)',
      'Evening',
    ])
    expect(items.map(b => b.getAttribute('aria-label'))).toEqual([
      null,
      'Move to Day 1 · Afternoon (swap with Forum)',
      'Move to Day 1 · Evening',
    ])
    expect(document.activeElement).toBe(items[1]) // first move target, never Remove
    click(button('Evening', menu))
    expect(h.onMoveSlot).toHaveBeenCalledWith('1-morning', 1, 'evening', 'menu')
    expect(document.querySelector('[role="menu"]')).toBeNull()
    expect(container.querySelector('[aria-live="polite"]').textContent).toBe('Moved Colosseum to Day 1 · Evening')
  })

  it('Escape closes the Move menu and returns focus to its button', () => {
    render(handlers())
    const move = button('Move', row('1-morning'))
    click(move)
    const item = document.querySelector('[role="menuitem"]')
    act(() => { item.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true })) })
    expect(document.querySelector('[role="menu"]')).toBeNull()
    expect(document.activeElement).toBe(move)
    expect(move.getAttribute('aria-expanded')).toBe('false')
  })

  it('"Remove from day" calls onRemoveSlot', () => {
    const h = handlers()
    render(h)
    click(button('Move', row('2-morning')))
    click(button('Remove from day'))
    expect(h.onRemoveSlot).toHaveBeenCalledWith('2-morning')
    expect(container.querySelector('[aria-live="polite"]').textContent).toBe('Removed Sagrada Familia from Day 2')
  })

  it('shows Free time for empty positions that accepts drops', () => {
    const h = handlers()
    render(h)
    const spot = free('2-evening')
    expect(spot.textContent).toContain('Free time')
    expect(free('1-morning')).toBeNull()
    const dt = transfer()
    fire(row('1-morning'), 'dragstart', dt)
    expect(fire(spot, 'dragover', dt).defaultPrevented).toBe(true)
    fire(spot, 'drop', dt)
    expect(h.onMoveSlot).toHaveBeenCalledWith('1-morning', 2, 'evening', 'drag')
  })

  it('does not invent placeholders for days without standard slots', () => {
    const data = { days: [...ITIN.days, { day_number: 3, slots: [] }, { day_number: 4, slots: [slot('late night', 'Club')] }] }
    render({ ...handlers(), data })
    expect(free('3-morning')).toBeNull()
    expect(free('4-morning')).toBeNull()
  })

  it('toolbar shows change count, Undo and Reset only when changed', () => {
    const h = handlers()
    render(h)
    expect(button('Reset')).toBeUndefined()
    expect(container.textContent).not.toMatch(/\d+ changes?/)

    const layout = moveSlot(ITIN, null, '1-morning', 2, 'afternoon')
    render({ ...h, selections: { itinerary_layout: layout }, canUndo: false })
    expect(container.textContent).toContain('2 changes')
    expect(button('Undo').disabled).toBe(true)
    render({ ...h, selections: { itinerary_layout: layout }, canUndo: true })
    click(button('Undo'))
    expect(h.onUndoLayout).toHaveBeenCalled()
    click(button('Reset'))
    expect(h.onResetLayout).toHaveBeenCalled()
  })

  it('keeps Undo reachable after a reset', () => {
    const h = handlers()
    render({ ...h, canUndo: true })
    expect(button('Reset')).toBeUndefined()
    click(button('Undo'))
    expect(h.onUndoLayout).toHaveBeenCalled()
  })

  it('lists removed activities with Restore', () => {
    const h = handlers()
    const layout = removeSlot(ITIN, null, '1-afternoon')
    render({ ...h, selections: { itinerary_layout: layout } })
    expect(container.textContent).toContain('1 change')
    const removed = container.querySelector('[data-removed-list]')
    expect(removed.textContent).toContain('Removed')
    expect(removed.textContent).toContain('Market')
    expect(row('1-afternoon')).toBeNull()
    expect(free('1-afternoon')).not.toBeNull()
    click(button('Restore', removed))
    expect(h.onRestoreSlot).toHaveBeenCalledWith('1-afternoon')
  })

  it('disables Restore when the original day is full', () => {
    let layout = removeSlot(ITIN, null, '1-afternoon')
    layout = moveSlot(ITIN, layout, '2-morning', 1, 'afternoon')
    render({ ...handlers(), selections: { itinerary_layout: layout } })
    const restore = button('Restore', container.querySelector('[data-removed-list]'))
    expect(restore.disabled).toBe(true)
    expect(restore.getAttribute('title')).toMatch(/Day 1/)
  })

  it('edit, note and Plan on a moved activity use its original key and current position', () => {
    const h = handlers()
    const layout = moveSlot(ITIN, null, '1-morning', 2, 'evening')
    const selections = {
      itinerary_layout: layout,
      itinerary_edits: { '1-morning': { activity: 'Cathedral tour', cost: 12 } },
      itinerary_notes: { '1-morning': 'bring hat' },
      itinerary_slots: [{ key: '1-morning' }],
    }
    render({ ...h, selections })
    const r = row('1-morning')
    expect(r.closest('[data-day]').dataset.day).toBe('2')
    expect(r.textContent).toContain('Cathedral tour')
    expect(r.textContent).toContain('bring hat')
    expect(r.textContent).toContain('In Plan')
    click(button('In Plan', r))
    expect(h.onSlotPlan).toHaveBeenCalledWith('1-morning', {
      key: '1-morning', day_number: 2, time_of_day: 'evening', activity: 'Cathedral tour', location: 'Cathedral St', estimated_cost_usd: 12,
      start_time: '18:30', end_time: '20:30', start_day_offset: 0, end_day_offset: 0, duration_hours: 2,
    })
    click(button('Note ✓', r))
    const textarea = row('1-morning').querySelector('textarea')
    expect(textarea.value).toBe('bring hat')
    click(button('Edited', row('1-morning')))
    const input = row('1-morning').querySelector('input[type="text"]')
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set
    act(() => {
      setter.call(input, 'Cathedral roof')
      input.dispatchEvent(new Event('input', { bubbles: true }))
    })
    expect(h.onSlotEdit).toHaveBeenCalledWith('1-morning', 'activity', 'Cathedral roof')
  })

  it('odd time-of-day slots have no handle or Move', () => {
    const data = { days: [{ day_number: 1, slots: [slot('morning', 'Walk'), slot('late night', 'Club')] }] }
    render({ ...handlers(), data })
    const odd = row('1-late night')
    expect(odd.getAttribute('draggable')).not.toBe('true')
    expect(odd.querySelector('[data-drag-handle]')).toBeNull()
    expect(button('Move', odd)).toBeUndefined()
    expect(button('Plan', odd)).toBeDefined()
    expect(button('Move', row('1-morning'))).toBeDefined()
  })
  it('menu entries equal the accepted drop targets, with empty and odd-only days', () => {
    const data = { days: [...ITIN.days, { day_number: 3, slots: [] }, { day_number: 4, slots: [slot('late night', 'Club')] }] }
    render({ ...handlers(), data })
    click(button('Move', row('1-morning')))
    const menuTargets = [...document.querySelectorAll('[role="menuitem"]')]
      .map((b) => b.getAttribute('aria-label') || '').filter((t) => t.startsWith('Move to Day ')).map(posOfLabel)
    act(() => { document.body.dispatchEvent(new MouseEvent('mousedown', { bubbles: true })) })
    const dt = transfer()
    fire(row('1-morning'), 'dragstart', dt)
    const zones = [...container.querySelectorAll('[data-slot-key], [data-free-slot]')]
    const accepted = zones
      .filter((el) => fire(el, 'dragover', dt).defaultPrevented)
      .map((el) => el.dataset.freeSlot || `${el.closest('[data-day]').dataset.day}-${el.dataset.time}`)
    expect(accepted.sort()).toEqual(menuTargets.sort())
    expect(menuTargets.some((p) => p.startsWith('3-') || p.startsWith('4-'))).toBe(false)
  })

  it('keeps the menu open on a blur with no related target and closes on outside mousedown or focus', () => {
    render(handlers())
    click(button('Move', row('1-morning')))
    const item = document.querySelector('[role="menuitem"]')
    act(() => { item.dispatchEvent(new FocusEvent('focusout', { bubbles: true, relatedTarget: null })) })
    expect(document.querySelector('[role="menu"]')).not.toBeNull()
    const md = new MouseEvent('mousedown', { bubbles: true, cancelable: true })
    item.dispatchEvent(md)
    expect(md.defaultPrevented).toBe(true)
    act(() => { document.body.dispatchEvent(new MouseEvent('mousedown', { bubbles: true })) })
    expect(document.querySelector('[role="menu"]')).toBeNull()

    click(button('Move', row('1-morning')))
    const outside = button('Plan', row('2-morning'))
    act(() => { outside.focus() })
    expect(document.querySelector('[role="menu"]')).toBeNull()
  })

  it('a row with its note open is not draggable', () => {
    render(handlers())
    click(button('Note', row('1-morning')))
    expect(row('1-morning').querySelector('textarea')).not.toBeNull()
    expect(row('1-morning').getAttribute('draggable')).not.toBe('true')
    expect(row('1-morning').querySelector('[data-drag-handle]')).toBeNull()
    const dt = transfer()
    fire(row('1-morning'), 'dragstart', dt)
    expect(dt.setData).not.toHaveBeenCalled()
  })

  it('focuses Undo after Remove from day and after restoring the last removed item', () => {
    act(() => root.render(<Stateful data={ITIN} />))
    click(button('Move', row('1-afternoon')))
    click(button('Remove from day'))
    expect(document.activeElement).toBe(button('Undo'))
    click(button('Restore', container.querySelector('[data-removed-list]')))
    expect(container.querySelector('[data-removed-list]')).toBeNull()
    expect(document.activeElement).toBe(button('Undo'))
  })

  it('focuses the section when there is no Undo after a removal', () => {
    const h = handlers()
    delete h.onUndoLayout
    render(h)
    click(button('Move', row('1-afternoon')))
    click(button('Remove from day'))
    expect(document.activeElement).toBe(container.querySelector('[data-itinerary-section]'))
  })

  it('after any Restore focuses Undo when enabled, else the section', () => {
    const h = handlers()
    const layout = removeSlot(ITIN, removeSlot(ITIN, null, '1-afternoon'), '1-evening')
    render({ ...h, selections: { itinerary_layout: layout }, canUndo: true })
    click(button('Restore', container.querySelector('[data-removed-list]')))
    expect(document.activeElement).toBe(button('Undo'))
    render({ ...h, selections: { itinerary_layout: layout }, canUndo: false })
    click(buttons(container.querySelector('[data-removed-list]')).filter((b) => b.textContent.trim() === 'Restore')[1])
    expect(document.activeElement).toBe(container.querySelector('[data-itinerary-section]'))
  })

  it('focuses the section after Reset or Undo hides the toolbar', () => {
    act(() => root.render(<Stateful data={ITIN} />))
    click(button('Move', row('1-afternoon')))
    click(button('Remove from day'))
    click(button('Undo'))
    expect(button('Undo')).toBeUndefined()
    expect(document.activeElement).toBe(container.querySelector('[data-itinerary-section]'))
    click(button('Move', row('1-afternoon')))
    click(button('Remove from day'))
    click(button('Move', row('1-morning')))
    click(button('Remove from day'))
    click(button('Undo'))
    expect(document.activeElement).toBe(button('Undo'))
    click(button('Reset'))
    expect(document.activeElement).toBe(button('Undo'))
  })

  it('names every row action and Restore after its activity, keeping the visible text', () => {
    const layout = removeSlot(ITIN, null, '1-afternoon')
    const selections = {
      itinerary_layout: layout,
      itinerary_edits: { '1-morning': { activity: 'Cathedral tour' } },
      itinerary_notes: { '1-morning': 'bring hat' },
      itinerary_slots: [{ key: '1-morning' }],
    }
    render({ ...handlers(), selections })
    const label = (text, scope) => button(text, scope).getAttribute('aria-label')
    expect(label('Edited', row('1-morning'))).toBe('Edit Cathedral tour')
    expect(label('Note ✓', row('1-morning'))).toBe('Edit note for Cathedral tour')
    expect(label('In Plan', row('1-morning'))).toBe('Remove Cathedral tour from plan')
    expect(label('Edit', row('1-evening'))).toBe('Edit Tapas')
    expect(label('Note', row('1-evening'))).toBe('Add note to Tapas')
    expect(label('Plan', row('1-evening'))).toBe('Add Tapas to plan')
    expect(label('Restore', container.querySelector('[data-removed-list]'))).toBe('Restore Market')
  })

  it('exposes day headings as labelled groups, a labelled Move button and a group toolbar', () => {
    act(() => root.render(<Stateful data={ITIN} />))
    click(button('Move', row('1-afternoon')))
    expect(button('Move', row('1-afternoon')).getAttribute('aria-label')).toBe('Move Market')
    const groups = [...document.querySelectorAll('[role="menu"] [role="group"]')]
    expect(groups.length).toBeGreaterThan(0)
    for (const g of groups) {
      const label = document.getElementById(g.getAttribute('aria-labelledby'))
      expect(label.textContent).toMatch(/^Day \d/)
      expect(g.querySelector('[role="menuitem"]')).not.toBeNull()
    }
    click(button('Remove from day'))
    expect(container.querySelector('[role="toolbar"]')).toBeNull()
    expect(container.querySelector('[role="group"][aria-label="Itinerary changes"]')).not.toBeNull()
  })

  it('places Free time where its time belongs relative to odd slots', () => {
    const data = { days: [{ day_number: 1, slots: [slot('morning', 'A'), slot('lunch', 'Lunch'), slot('evening', 'B')] }, ITIN.days[1]] }
    const layout = removeSlot(data, null, '1-morning')
    render({ ...handlers(), data, selections: { itinerary_layout: layout } })
    const order = [...container.querySelector('[data-day="1"]').querySelectorAll('[data-slot-key], [data-free-slot]')]
      .map((el) => el.dataset.freeSlot ? `free:${el.dataset.freeSlot}` : el.dataset.slotKey)
    expect(order).toEqual(['free:1-morning', '1-lunch', 'free:1-afternoon', '1-evening'])
  })

  describe('estimated times', () => {
    const KM_PER_DEG = (6371 * Math.PI) / 180
    const at = (km) => ({ lat: 41.38 + km / 1.3 / KM_PER_DEG, lng: 2.17 })
    const GEO = {
      days: [
        { day_number: 1, slots: [
          { ...slot('morning', 'Cathedral'), ...at(0) },
          { ...slot('afternoon', 'Market'), ...at(0.8) },
          { ...slot('evening', 'Tapas'), ...at(4.8) },
        ] },
        { day_number: 2, slots: [slot('morning', 'Long walk'), slot('afternoon', 'Late lunch')] },
      ],
    }
    GEO.days[1].slots[0].duration_hours = 5
    const timeOf = (key) => row(key).querySelector('[data-slot-time]')?.textContent

    it('shows each row\'s start–end under its time of day', () => {
      render(handlers())
      expect(timeOf('1-morning')).toBe('09:00–11:00')
      expect(timeOf('1-afternoon')).toBe('13:30–15:30')
      expect(timeOf('1-evening')).toBe('18:30–20:30')
      expect(container.textContent).toContain('Times are estimates based on typical durations and distances.')
    })

    it('re-times activities after a move', () => {
      const layout = moveSlot(ITIN, null, '1-morning', 2, 'afternoon') // swaps with Park Guell
      render({ ...handlers(), selections: { itinerary_layout: layout } })
      expect(timeOf('1-morning')).toBe('13:30–15:30')
      expect(timeOf('2-afternoon')).toBe('09:00–11:00')
    })

    it('shows travel between stops outside the draggable rows', () => {
      render({ ...handlers(), data: GEO })
      const lines = [...container.querySelectorAll('[data-day="1"] [data-transit]')]
      expect(lines.map((l) => l.textContent)).toEqual(['🚶 15 min walk · 0.8 km', '🚇 ~25 min by transit'])
      for (const line of lines) {
        expect(line.closest('[data-slot-key]')).toBeNull()
        expect(line.closest('[draggable]')).toBeNull()
      }
      // unknown coordinates: no line at all
      expect(container.querySelector('[data-day="2"] [data-transit]')).toBeNull()
    })

    it('hides travel lines on a day listed out of its timed order', () => {
      const data = { days: [
        { day_number: 1, slots: [{ ...slot('evening', 'Tapas'), ...at(0.8) }, { ...slot('morning', 'Cathedral'), ...at(0) }] },
        { ...GEO.days[0], day_number: 2 },
      ] }
      render({ ...handlers(), data })
      // Tapas (listed first) is timed after Cathedral: no line may claim travel from a stop shown below it
      expect(row('1-evening').querySelector('[data-slot-time]').textContent).toBe('18:30–20:30')
      expect(container.querySelector('[data-day="1"] [data-transit]')).toBeNull()
      expect(container.querySelectorAll('[data-day="2"] [data-transit]')).toHaveLength(2)
    })

    it('flags a tight day, naming the edited activity', () => {
      const edits = { '2-afternoon': { activity: 'Tapas lunch' } }
      render({ ...handlers(), data: GEO, selections: { itinerary_edits: edits } })
      const warning = container.querySelector('[data-day="2"] [data-schedule-warnings]')
      expect(warning.textContent).toContain('Tight schedule')
      expect(warning.textContent).toContain('Tapas lunch starts at 14:20 — later than planned')
      expect(container.querySelector('[data-day="1"] [data-schedule-warnings]')).toBeNull()
    })

    it('a transit line does not get in the way of dropping on the next row or a placeholder', () => {
      const h = handlers()
      const layout = removeSlot(GEO, null, '1-afternoon')
      render({ ...h, data: GEO, selections: { itinerary_layout: layout } })
      const dt = transfer()
      fire(row('1-morning'), 'dragstart', dt)
      const spot = free('1-afternoon')
      expect(fire(spot, 'dragover', dt).defaultPrevented).toBe(true)
      fire(spot, 'drop', dt)
      expect(h.onMoveSlot).toHaveBeenCalledWith('1-morning', 1, 'afternoon', 'drag')
    })
  })

  it('shows the original name for an empty-string activity edit', () => {
    render({ ...handlers(), selections: { itinerary_edits: { '1-afternoon': { activity: '' } } } })
    expect([...activities(0)].map(n => n.textContent)).toEqual(['Cathedral', 'Market', 'Tapas'])
    expect(button('Plan', row('1-afternoon')).getAttribute('aria-label')).toBe('Add Market to plan')
  })

  it('dragend clears the drag state', () => {
    render(handlers())
    const dt = transfer()
    fire(row('1-morning'), 'dragstart', dt)
    fire(row('2-afternoon'), 'dragover', dt)
    expect(row('1-morning').className).toContain('opacity-50')
    expect(row('2-afternoon').className).toContain('ring-teal-400')
    fire(row('1-morning'), 'dragend', dt)
    expect(row('1-morning').className).not.toContain('opacity-50')
    expect(container.querySelector('.ring-teal-400')).toBeNull()
    expect(fire(row('2-afternoon'), 'dragover', dt).defaultPrevented).toBe(false)
  })

  it('dropping a slot on its own position does nothing', () => {
    const h = handlers()
    render(h)
    const dt = transfer()
    fire(row('1-morning'), 'dragstart', dt)
    expect(fire(row('1-morning'), 'dragover', dt).defaultPrevented).toBe(false)
    fire(row('1-morning'), 'drop', dt)
    expect(h.onMoveSlot).not.toHaveBeenCalled()
  })

  it('focuses the moved row\'s Move button after a menu move', () => {
    act(() => root.render(<Stateful data={ITIN} />))
    click(button('Move', row('1-morning')))
    click(document.querySelector('[aria-label="Move to Day 2 · Evening"]'))
    const moved = row('1-morning')
    expect(moved.closest('[data-day]').dataset.day).toBe('2')
    expect(document.activeElement).toBe(button('Move', moved))
  })
  describe('menu placement and grouping', () => {
    const viewport = { w: window.innerWidth, h: window.innerHeight }
    const setViewport = (w, h) => {
      Object.defineProperty(window, 'innerWidth', { value: w, configurable: true, writable: true })
      Object.defineProperty(window, 'innerHeight', { value: h, configurable: true, writable: true })
    }
    const anchorAt = (el, top, right = 600) => {
      el.getBoundingClientRect = () => ({ top, bottom: top + 30, left: right - 60, right, width: 60, height: 30, x: right - 60, y: top })
    }
    afterEach(() => setViewport(viewport.w, viewport.h))

    it('opens fixed below the button, right-aligned, outside the clipping card', () => {
      setViewport(1024, 800)
      render(handlers())
      const move = button('Move', row('1-morning'))
      anchorAt(move, 100, 600)
      click(move)
      const menu = document.querySelector('[role="menu"]')
      expect(menu.style.position).toBe('fixed')
      expect(menu.style.top).toBe('134px')
      expect(menu.style.bottom).toBe('')
      expect(menu.style.left).toBe(`${600 - 256}px`)
      expect(menu.style.maxHeight).toBe('360px')
      expect(container.contains(menu)).toBe(false)
    })

    it('flips above when the button is near the bottom and stays in the viewport', () => {
      setViewport(300, 800)
      render(handlers())
      const move = button('Move', row('1-morning'))
      anchorAt(move, 700, 100)
      click(move)
      const menu = document.querySelector('[role="menu"]')
      expect(menu.style.position).toBe('fixed')
      expect(menu.style.top).toBe('')
      expect(menu.style.bottom).toBe(`${800 - 700 + 4}px`)
      expect(menu.style.maxHeight).toBe('360px')
      expect(menu.style.left).toBe('8px')
      expect(menu.style.width).toBe('256px')
    })

    it('puts Remove first and groups targets under day headings', () => {
      render({ ...handlers(), data: MULTI })
      click(button('Move', row('2-morning')))
      const menu = document.querySelector('[role="menu"]')
      expect(menu.querySelector('[role="menuitem"]').textContent).toBe('Remove from day')
      expect(menu.querySelector('[role="separator"]')).not.toBeNull()
      const headings = [...menu.querySelectorAll('[role="group"] > [id]')].map((h) => h.textContent)
      expect(headings).toEqual(['Day 2 · Florence'])
      expect(button('Afternoon (swap with Duomo)', menu).getAttribute('aria-label')).toBe('Move to Day 2 · Afternoon (swap with Duomo)')

      act(() => { document.body.dispatchEvent(new MouseEvent('mousedown', { bubbles: true })) })
      render({ ...handlers() })
      click(button('Move', row('1-morning')))
      const days = [...document.querySelectorAll('[role="menu"] [role="group"] > [id]')].map((h) => h.textContent)
      expect(days).toEqual(['Day 1', 'Day 2'])
    })

    describe('following the page', () => {
      beforeEach(() => {
        setViewport(1024, 800)
        vi.stubGlobal('requestAnimationFrame', (cb) => { cb(0); return 1 })
        vi.stubGlobal('cancelAnimationFrame', () => {})
      })
      afterEach(() => vi.unstubAllGlobals())

      it('repositions on page scroll while the button is visible, ignores scroll inside the menu', () => {
        render(handlers())
        const move = button('Move', row('1-morning'))
        anchorAt(move, 100)
        click(move)
        const menu = document.querySelector('[role="menu"]')
        expect(menu.style.top).toBe('134px')
        act(() => { menu.dispatchEvent(new Event('scroll')) })
        expect(document.querySelector('[role="menu"]')).not.toBeNull()
        anchorAt(move, 40)
        act(() => { document.dispatchEvent(new Event('scroll')) })
        expect(document.querySelector('[role="menu"]')).not.toBeNull()
        expect(document.querySelector('[role="menu"]').style.top).toBe('74px')
        anchorAt(move, 300)
        act(() => { window.dispatchEvent(new Event('resize')) })
        expect(document.querySelector('[role="menu"]').style.top).toBe('334px')
      })

      it('closes once the button has scrolled entirely out of view', () => {
        render(handlers())
        const move = button('Move', row('1-morning'))
        anchorAt(move, 100)
        click(move)
        anchorAt(move, -200)
        act(() => { document.dispatchEvent(new Event('scroll')) })
        expect(document.querySelector('[role="menu"]')).toBeNull()

        anchorAt(move, 100)
        click(move)
        anchorAt(move, 900)
        act(() => { window.dispatchEvent(new Event('resize')) })
        expect(document.querySelector('[role="menu"]')).toBeNull()
      })
    })

    it('does not re-subscribe its listeners on every render', () => {
      const h = handlers()
      render(h)
      click(button('Move', row('1-morning')))
      const add = vi.spyOn(document, 'addEventListener')
      render({ ...h, selections: { itinerary_notes: {} } })
      expect(add.mock.calls.filter(([type]) => type === 'scroll')).toEqual([])
      expect(document.querySelector('[role="menu"]')).not.toBeNull()
    })
  })
  it('Tab and Shift+Tab close the menu and hand focus to the Move button', () => {
    render(handlers())
    for (const shiftKey of [false, true]) {
      const move = button('Move', row('1-morning'))
      click(move)
      const item = document.querySelectorAll('[role="menuitem"]')[1]
      const evt = new KeyboardEvent('keydown', { key: 'Tab', shiftKey, bubbles: true, cancelable: true })
      act(() => { item.dispatchEvent(evt) })
      expect(evt.defaultPrevented).toBe(false)
      expect(document.querySelector('[role="menu"]')).toBeNull()
      expect(document.activeElement).toBe(move)
    }
  })

  it('focuses the first move target on open, never Remove from day', () => {
    const data = { days: [{ day_number: 1, city: 'Rome', slots: [slot('morning', 'A'), slot('afternoon', 'B'), slot('evening', 'C')] }] }
    let layout = removeSlot(data, null, '1-afternoon')
    layout = removeSlot(data, layout, '1-evening')
    // a movable slot always has targets on its own day, so Remove is never focused first
    render({ ...handlers(), data, selections: { itinerary_layout: layout } })
    expect(button('Move', row('1-morning'))).toBeDefined()
    click(button('Move', row('1-morning')))
    const items = [...document.querySelectorAll('[role="menuitem"]')]
    expect(items.map((b) => b.textContent)).toEqual(['Remove from day', 'Afternoon', 'Evening'])
    expect(document.activeElement).toBe(items[1])
  })

  it('clears an open menu when editing becomes unavailable', () => {
    const h = handlers()
    render(h)
    click(button('Move', row('1-morning')))
    expect(document.querySelector('[role="menu"]')).not.toBeNull()
    render({ onNoteChange: h.onNoteChange, onSlotEdit: h.onSlotEdit, onSlotPlan: h.onSlotPlan })
    expect(document.querySelector('[role="menu"]')).toBeNull()
    render(h)
    expect(document.querySelector('[role="menu"]')).toBeNull()
    expect(button('Move', row('1-morning')).getAttribute('aria-expanded')).toBe('false')
  })
})
