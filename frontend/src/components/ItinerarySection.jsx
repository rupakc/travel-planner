import { Fragment, useCallback, useEffect, useId, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import {
  DollarSign, Check, MapPin, PenLine, MessageSquare, Plus,
  GripVertical, ArrowRightLeft, Undo2, RotateCcw,
} from 'lucide-react'
import TripMap from './TripMap'
import {
  TIMES, slotKey, slotRanks, arrangeItinerary, moveTargets, restoreSlot, layoutChangeCount,
} from '../utils/itineraryLayout'
import { listedInScheduleOrder, scheduleDays, timeRange, transitLabel } from '../utils/schedule'

// Custom MIME so the drawer (which treats application/json as a plan) never
// mistakes an itinerary drag for a plan drop.
const SLOT_MIME = 'application/x-itinerary-slot'
const DROP_HIGHLIGHT = 'ring-2 ring-teal-400 bg-teal-50'
const SLOT_ICONS = { morning: '🌅', afternoon: '☀️', evening: '🌙' }

const timeLabel = (tod) => tod.charAt(0).toUpperCase() + tod.slice(1)
const positionLabel = (dayNumber, tod) => `Day ${dayNumber} · ${timeLabel(tod)}`
const FOCUS_UNDO = Symbol('undo')
const carriesSlot = (e) => Array.from(e.dataTransfer?.types || []).includes(SLOT_MIME)

// Rows for one arranged day: its slots plus a "Free time" row for every
// standard time no movable activity occupies. Like positions in
// itineraryLayout, placeholders exist only on days that originally had at
// least one standard-time slot. A placeholder sits where its time ranks
// relative to odd/duplicate slots (the same rule arrangeItinerary sorts by).
function dayRows(day, originalDay, isMovable, withPlaceholders) {
  const slots = day.slots || []
  const rows = slots.map((slot) => ({ slot }))
  if (!withPlaceholders || !(originalDay?.slots || []).some((s) => TIMES.includes(s.time_of_day))) return rows
  const ranks = slotRanks(originalDay)
  const rankOf = (slot) => (isMovable(slot.key) ? TIMES.indexOf(slot.time_of_day) : ranks.get(slot.key) ?? -0.5)
  const occupied = new Set(slots.filter((s) => isMovable(s.key)).map((s) => s.time_of_day))
  TIMES.forEach((tod, rank) => {
    if (occupied.has(tod)) return
    const at = rows.findIndex((row) => row.slot && rankOf(row.slot) > rank)
    rows.splice(at < 0 ? rows.length : at, 0, { free: tod })
  })
  return rows
}

const MENU_WIDTH = 256
const MENU_MAX_HEIGHT = 360
const MENU_MARGIN = 8 // from the viewport edges
const MENU_GAP = 4 // from the Move button
const MENU_MIN_BELOW = 240

// Fixed placement next to the Move button: below and right-aligned, flipped
// above when there's little room below and more above; kept on screen.
function menuPlacement(rect, viewportWidth, viewportHeight) {
  const below = viewportHeight - rect.bottom - MENU_GAP - MENU_MARGIN
  const above = rect.top - MENU_GAP - MENU_MARGIN
  const up = below < MENU_MIN_BELOW && above > below
  const width = Math.min(MENU_WIDTH, viewportWidth - 2 * MENU_MARGIN)
  const left = Math.max(MENU_MARGIN, Math.min(rect.right - width, viewportWidth - MENU_MARGIN - width))
  const maxHeight = Math.max(0, Math.min(MENU_MAX_HEIGHT, up ? above : below))
  return up
    ? { position: 'fixed', left, width, maxHeight, bottom: viewportHeight - rect.top + MENU_GAP }
    : { position: 'fixed', left, width, maxHeight, top: rect.bottom + MENU_GAP }
}

// Portalled to <body> with fixed positioning: the section cards clip
// (overflow-hidden) and keep a transform from their entry animation, so an
// in-place menu would be cut off. Closes on Escape (returning focus), a
// pointer press outside the menu and its button, focus landing outside them,
// Tab/Shift+Tab (focus goes back to the button), and the button scrolling
// fully out of view; otherwise it follows the button on scroll/resize. A blur
// with no new focus target never closes it (Safari doesn't focus buttons on click).
const offScreen = (rect) => rect.bottom < 0 || rect.top > window.innerHeight
  || rect.right < 0 || rect.left > window.innerWidth

function MoveMenu({ label, anchorRect, anchorKey, getAnchor, removeItem, groups, onClose, onDismiss }) {
  const menuRef = useRef(null)
  const idBase = useId()
  const [rect, setRect] = useState(anchorRect)
  useEffect(() => {
    // First MOVE target, so open-then-Enter can never remove the activity.
    const menu = menuRef.current
    const first = menu?.querySelector('[data-move-target]') || menu?.querySelector('[role="menuitem"]')
    first?.focus({ preventScroll: true })
  }, [])
  useEffect(() => {
    const anchor = () => getAnchor(anchorKey)
    const inside = (node) => menuRef.current?.contains(node) || anchor()?.contains(node)
    const onPress = (e) => { if (!inside(e.target)) onDismiss() }
    const onFocusIn = (e) => { if (e.target instanceof Node && !inside(e.target)) onDismiss() }
    // Follow the button on page scroll/resize (once per frame); close only
    // when the button has left the viewport entirely.
    let pending = false
    let frame = 0
    const follow = (e) => {
      if (e.type === 'scroll' && menuRef.current?.contains(e.target)) return
      if (pending) return
      pending = true
      frame = window.requestAnimationFrame(() => {
        pending = false
        const el = anchor()
        if (!el) return
        const next = el.getBoundingClientRect()
        if (offScreen(next)) onDismiss()
        else setRect(next)
      })
    }
    document.addEventListener('pointerdown', onPress)
    document.addEventListener('mousedown', onPress)
    document.addEventListener('focusin', onFocusIn)
    document.addEventListener('scroll', follow, true)
    window.addEventListener('resize', follow)
    return () => {
      if (pending) window.cancelAnimationFrame(frame)
      document.removeEventListener('pointerdown', onPress)
      document.removeEventListener('mousedown', onPress)
      document.removeEventListener('focusin', onFocusIn)
      document.removeEventListener('scroll', follow, true)
      window.removeEventListener('resize', follow)
    }
  }, [anchorKey, getAnchor, onDismiss])

  const onKeyDown = (e) => {
    if (e.key === 'Tab') {
      // No preventDefault: focus returns to the Move button and the browser
      // carries on tabbing from there.
      onClose()
      return
    }
    if (e.key === 'Escape') {
      e.preventDefault()
      e.stopPropagation()
      onClose()
      return
    }
    if (e.key !== 'ArrowDown' && e.key !== 'ArrowUp') return
    e.preventDefault()
    const all = [...menuRef.current.querySelectorAll('[role="menuitem"]')]
    const at = all.indexOf(document.activeElement)
    const step = e.key === 'ArrowDown' ? 1 : -1
    all[(at + step + all.length) % all.length]?.focus({ preventScroll: true })
  }

  const itemButton = (item, className) => (
    <button key={item.id} type="button" role="menuitem" aria-label={item.ariaLabel} onClick={item.onSelect}
      data-move-target={item.isTarget ? '' : undefined}
      onMouseDown={(e) => e.preventDefault()}
      className={`block w-full text-left px-3 py-1.5 text-xs focus:outline-none ${className}`}>
      {item.label}
    </button>
  )

  return createPortal(
    <div ref={menuRef} role="menu" aria-label={label} onKeyDown={onKeyDown}
      style={menuPlacement(rect, window.innerWidth, window.innerHeight)}
      className="z-50 overflow-y-auto bg-white border border-gray-200 rounded-lg shadow-lg py-1">
      {removeItem && (
        <>
          {itemButton(removeItem, 'text-red-600 hover:bg-red-50 focus:bg-red-50')}
          {groups.length > 0 && <div role="separator" className="my-1 border-t border-gray-100" />}
        </>
      )}
      {groups.map((group) => (
        <div key={group.day_number} role="group" aria-labelledby={`${idBase}-day-${group.day_number}`}>
          <div id={`${idBase}-day-${group.day_number}`} className="px-3 pt-2 pb-0.5 text-[10px] font-semibold uppercase tracking-wide text-gray-400">
            {group.heading}
          </div>
          {group.items.map((item) => itemButton(item, 'pl-5 text-gray-700 hover:bg-teal-50 focus:bg-teal-50'))}
        </div>
      ))}
    </div>,
    document.body,
  )
}

export default function ItinerarySection({
  data, selections, onNoteChange, onSlotEdit, onSlotPlan,
  onMoveSlot, onRemoveSlot, onRestoreSlot, onUndoLayout, onResetLayout, canUndo = false, editingDisabledReason = '',
}) {
  const [editingSlot, setEditingSlot] = useState(null) // key of slot being edited
  const [openNote,    setOpenNote]    = useState(null)
  const [menuFor,     setMenuFor]     = useState(null) // key whose Move menu is open
  const [menuAnchor,  setMenuAnchor]  = useState(null) // Move button's rect when it opened
  const [dragKey,     setDragKey]     = useState(null)
  const [dropAt,      setDropAt]      = useState(null) // highlighted position
  const [status,      setStatus]      = useState('')
  const moveButtons = useRef({})
  const undoButton = useRef(null)
  const sectionRef = useRef(null)
  const focusAfterRender = useRef(null) // slot key (its Move button) or FOCUS_UNDO
  const dismissMenu = useCallback(() => setMenuFor(null), [])
  const getMoveButton = useCallback((key) => moveButtons.current[key], [])

  const layout = selections.itinerary_layout
  const edits = selections.itinerary_edits
  const editable = typeof onMoveSlot === 'function'
  // Editing switched off (e.g. a saved plan opened): drop any open menu.
  if (!editable && (menuFor !== null || menuAnchor !== null)) {
    setMenuFor(null)
    setMenuAnchor(null)
  }
  const arranged = useMemo(() => arrangeItinerary(data, layout, edits), [data, layout, edits])
  // Estimated times follow every move, removal and rename
  const scheduledDays = useMemo(() => scheduleDays(arranged.days, edits), [arranged, edits])
  const hasTimes = scheduledDays.some((day) => (day.slots || []).some((slot) => slot.start_time))
  // A travel line must come from the stop listed above it: none on days listed out of timed order
  const outOfOrderDays = new Set(scheduledDays.filter((day) => !listedInScheduleOrder(day)).map((day) => day.day_number))
  // One source of truth for drag validity AND the Move menu (city rule included).
  const targetsByKey = useMemo(() => {
    const map = new Map()
    if (!editable) return map
    for (const day of arranged.days) {
      for (const slot of day.slots || []) map.set(slot.key, moveTargets(data, layout, slot.key))
    }
    return map
  }, [editable, arranged, data, layout])

  useEffect(() => {
    const target = focusAfterRender.current
    if (!target) return
    focusAfterRender.current = null
    if (target !== FOCUS_UNDO) {
      moveButtons.current[target]?.focus()
    } else if (undoButton.current && !undoButton.current.disabled) {
      undoButton.current.focus()
    } else {
      sectionRef.current?.focus()
    }
  })

  if (!data?.days?.length) return <div className="p-4 text-sm text-gray-500">No itinerary available</div>

  const isMovable = (key) => (targetsByKey.get(key) || []).length > 0
  const findTarget = (key, dayNumber, tod) => (targetsByKey.get(key) || [])
    .find((t) => t.day_number === dayNumber && t.time_of_day === tod)
  const activityName = (key, fallback) => edits?.[key]?.activity || fallback
  const changeCount = editable ? layoutChangeCount(data, layout) : 0

  const move = (key, name, target, method) => {
    onMoveSlot(key, target.day_number, target.time_of_day, method)
    const swap = target.swapWith ? ` (swapped with ${activityName(target.swapWith.key, target.swapWith.activity)})` : ''
    setStatus(`Moved ${name} to ${positionLabel(target.day_number, target.time_of_day)}${swap}`)
  }

  const closeMenu = (key) => {
    setMenuFor(null)
    moveButtons.current[key]?.focus()
  }

  const dropZoneProps = (dayNumber, tod) => {
    if (!editable) return {}
    const pos = slotKey(dayNumber, tod)
    return {
      onDragOver: (e) => {
        if (!dragKey || !carriesSlot(e) || !findTarget(dragKey, dayNumber, tod)) return
        e.preventDefault()
        e.dataTransfer.dropEffect = 'move'
        if (dropAt !== pos) setDropAt(pos)
      },
      onDragLeave: (e) => {
        if (e.currentTarget.contains(e.relatedTarget)) return
        setDropAt((at) => (at === pos ? null : at))
      },
      onDrop: (e) => {
        if (!carriesSlot(e)) return
        const key = e.dataTransfer.getData(SLOT_MIME)
        const target = key && findTarget(key, dayNumber, tod)
        setDropAt(null)
        setDragKey(null)
        if (!target) return
        e.preventDefault()
        const slot = arranged.days.flatMap((d) => d.slots || []).find((s) => s.key === key)
        move(key, activityName(key, slot?.activity), target, 'drag')
      },
    }
  }

  const removed = arranged.removed || []

  return (
    <div ref={sectionRef} data-itinerary-section tabIndex={editable ? -1 : undefined} className="p-4 space-y-4 focus:outline-none">
      {editingDisabledReason && <p data-editing-disabled className="text-xs text-gray-500">{editingDisabledReason}</p>}
      {/* Map at the top */}
      <TripMap days={arranged.days} />

      {/* Header row */}
      <div className="flex items-center justify-between">
        {arranged.total_estimated_cost_usd > 0 && (
          <div className="flex items-center gap-2 p-2.5 bg-teal-50 rounded-lg border border-teal-200 text-sm">
            <DollarSign size={13} className="text-teal-600" />
            <span className="text-teal-800 font-medium">Est. itinerary cost: ${arranged.total_estimated_cost_usd.toLocaleString()}</span>
          </div>
        )}
        {data.source === 'template' && (
          <span className="text-xs text-amber-600 bg-amber-50 border border-amber-200 px-2 py-1 rounded-full">Auto-generated — click any slot to edit</span>
        )}
      </div>

      {hasTimes && <p data-times-note className="text-xs text-gray-400">Times are estimates based on typical durations and distances.</p>}

      {/* Layout toolbar */}
      {editable && (changeCount > 0 || canUndo) && (
        <div role="group" aria-label="Itinerary changes"
          className="flex items-center gap-2 px-3 py-2 rounded-lg border border-teal-200 bg-teal-50/60 text-xs">
          {changeCount > 0 && (
            <span className="font-medium text-teal-800">{changeCount} {changeCount === 1 ? 'change' : 'changes'}</span>
          )}
          <span className="flex-1" />
          {onUndoLayout && (
            <button type="button" ref={undoButton} disabled={!canUndo}
              onClick={() => { focusAfterRender.current = FOCUS_UNDO; onUndoLayout(); setStatus('Undid the last change') }}
              className="flex items-center gap-1 px-2.5 py-1 rounded-full font-medium bg-white border border-gray-200 text-gray-600 hover:bg-teal-100 hover:text-teal-700 disabled:opacity-40 disabled:hover:bg-white disabled:hover:text-gray-600">
              <Undo2 size={10} /> Undo
            </button>
          )}
          {changeCount > 0 && onResetLayout && (
            <button type="button"
              onClick={() => { focusAfterRender.current = FOCUS_UNDO; onResetLayout(); setStatus('Itinerary reset to the original order') }}
              className="flex items-center gap-1 px-2.5 py-1 rounded-full font-medium bg-white border border-gray-200 text-gray-600 hover:bg-teal-100 hover:text-teal-700">
              <RotateCcw size={10} /> Reset
            </button>
          )}
        </div>
      )}

      {scheduledDays.map((day, dayIndex) => (
        <div key={day.day_number} data-day={day.day_number} className="border border-gray-200 rounded-xl overflow-hidden">
          {/* Day header */}
          <div className={`flex items-center justify-between px-4 py-3 text-white ${day.city ? 'bg-gradient-to-r from-indigo-700 to-indigo-800' : 'bg-gradient-to-r from-teal-600 to-teal-700'}`}>
            <div>
              <span className="font-bold">Day {day.day_number}</span>
              {day.date && <span className="ml-2 text-teal-200 text-sm">{day.date}</span>}
              {day.city && (
                <span className="ml-2 bg-white/20 px-1.5 py-0.5 rounded text-[10px] font-medium">
                  {day.city}
                </span>
              )}
            </div>
            <div className="text-right">
              {day.theme && <p className="text-sm font-medium">{day.theme}</p>}
              {day.daily_estimated_cost_usd > 0 && <p className="text-xs text-teal-200">${day.daily_estimated_cost_usd} est.</p>}
            </div>
          </div>

          {day.schedule_warnings?.length > 0 && (
            <div data-schedule-warnings className="px-4 py-2 bg-amber-50 border-b border-amber-200 text-xs text-amber-800">
              <span className="inline-block mb-1 px-2 py-0.5 rounded-full bg-amber-100 border border-amber-300 font-semibold">Tight schedule</span>
              <ul className="list-disc pl-4 space-y-0.5">
                {day.schedule_warnings.map((warning, i) => <li key={i}>{warning}</li>)}
              </ul>
            </div>
          )}

          {/* Slots */}
          <div className="divide-y divide-gray-100">
            {dayRows(day, data.days[dayIndex], isMovable, editable).map((row) => {
              if (row.free) {
                const pos = slotKey(day.day_number, row.free)
                return (
                  <div key={`free-${pos}`} data-free-slot={pos} {...dropZoneProps(day.day_number, row.free)}
                    className={`px-4 py-3 transition-colors ${dropAt === pos ? DROP_HIGHLIGHT : ''}`}>
                    <div className="flex gap-3 items-center">
                      <span className="w-4 shrink-0" />
                      <div className="w-20 shrink-0 text-sm text-gray-400 font-medium capitalize flex items-center gap-1">
                        <span>{SLOT_ICONS[row.free]}</span>
                        <span>{row.free}</span>
                      </div>
                      <p className="flex-1 text-sm text-gray-400 italic border border-dashed border-gray-200 rounded-lg px-3 py-1.5">Free time</p>
                    </div>
                  </div>
                )
              }

              const { slot } = row
              const key = slot.key
              const edit  = edits?.[key] || {}
              const note  = selections.itinerary_notes?.[key] || ''
              const isEditing  = editingSlot === key
              const isNoteOpen = openNote === key
              const movable = isMovable(key)
              // Never draggable while a text field in the row is open.
              const canDrag = movable && !isEditing && !isNoteOpen
              const menuOpen = menuFor === key
              const pos = slotKey(day.day_number, slot.time_of_day)

              // Merge saved edits over original slot data
              const activity = edit.activity  || slot.activity
              const location = edit.location  ?? slot.location
              const cost     = edit.cost      ?? slot.estimated_cost_usd
              const inPlan   = selections.itinerary_slots?.some(s => s.key === key)

              const menuGroups = []
              for (const t of movable ? targetsByKey.get(key) : []) {
                let group = menuGroups.at(-1)
                if (group?.day_number !== t.day_number) {
                  const city = arranged.days.find((d) => d.day_number === t.day_number)?.city
                  group = { day_number: t.day_number, heading: `Day ${t.day_number}${city ? ` · ${city}` : ''}`, items: [] }
                  menuGroups.push(group)
                }
                const swap = t.swapWith ? ` (swap with ${activityName(t.swapWith.key, t.swapWith.activity)})` : ''
                group.items.push({
                  id: slotKey(t.day_number, t.time_of_day),
                  label: `${timeLabel(t.time_of_day)}${swap}`,
                  isTarget: true,
                  ariaLabel: `Move to ${positionLabel(t.day_number, t.time_of_day)}${swap}`,
                  onSelect: () => {
                    focusAfterRender.current = key
                    setMenuFor(null)
                    move(key, activity, t, 'menu')
                  },
                })
              }
              const removeItem = movable && onRemoveSlot ? {
                id: 'remove',
                label: 'Remove from day',
                onSelect: () => {
                  focusAfterRender.current = FOCUS_UNDO
                  setMenuFor(null)
                  onRemoveSlot(key)
                  setStatus(`Removed ${activity} from Day ${day.day_number}`)
                },
              } : null

              const range = timeRange(slot)
              const transit = outOfOrderDays.has(day.day_number) ? '' : transitLabel(slot.transit_from_prev)

              return (
                <Fragment key={key}>
                  {/* Travel from the previous stop: outside the row, so drag and drop targets stay rows */}
                  {transit && (
                    <p data-transit className="px-4 py-1 text-[11px] text-gray-400 bg-gray-50/60 tabular-nums">
                      <span className="inline-block w-4 mr-3" aria-hidden="true" />{transit}
                    </p>
                  )}
                  <div data-slot-key={key} data-time={slot.time_of_day}
                    draggable={canDrag ? true : undefined}
                    onDragStart={canDrag ? (e) => {
                      e.dataTransfer.setData(SLOT_MIME, key)
                      e.dataTransfer.effectAllowed = 'move'
                      setDragKey(key)
                      setMenuFor(null)
                    } : undefined}
                    onDragEnd={movable ? () => { setDragKey(null); setDropAt(null) } : undefined}
                    {...(movable ? dropZoneProps(day.day_number, slot.time_of_day) : {})}
                    className={`px-4 py-3 transition-colors ${dropAt === pos && movable ? DROP_HIGHLIGHT : isEditing ? 'bg-teal-50' : 'hover:bg-gray-50'} ${dragKey === key ? 'opacity-50' : ''}`}>
                    <div className="flex gap-3">
                      {editable && (canDrag ? (
                        <span data-drag-handle aria-hidden="true" title="Drag to move"
                          className="w-4 shrink-0 flex items-center text-gray-300 hover:text-gray-500 cursor-grab active:cursor-grabbing">
                          <GripVertical size={14} aria-hidden="true" />
                        </span>
                      ) : <span className="w-4 shrink-0" />)}

                      {/* Time icon, label and estimated times */}
                      <div className="w-20 shrink-0">
                        <div className="text-sm text-gray-500 font-medium capitalize flex items-center gap-1">
                          <span>{SLOT_ICONS[slot.time_of_day]}</span>
                          <span>{slot.time_of_day}</span>
                        </div>
                        {range && <p data-slot-time className="mt-0.5 text-[11px] text-gray-400 tabular-nums">{range}</p>}
                      </div>

                      {/* Content — view or edit */}
                      <div className="flex-1 min-w-0">
                        {isEditing ? (
                          <div className="space-y-2">
                            <div>
                              <label className="text-xs text-teal-600 font-medium">Activity</label>
                              <input
                                autoFocus
                                type="text"
                                value={edit.activity ?? slot.activity}
                                onChange={e => onSlotEdit(key, 'activity', e.target.value)}
                                className="mt-0.5 w-full text-sm border border-teal-300 rounded-lg px-2.5 py-1.5 focus:outline-none focus:ring-1 focus:ring-teal-400 bg-white"
                              />
                            </div>
                            <div className="grid grid-cols-2 gap-2">
                              <div>
                                <label className="text-xs text-teal-600 font-medium">Location</label>
                                <input
                                  type="text"
                                  value={edit.location ?? slot.location ?? ''}
                                  onChange={e => onSlotEdit(key, 'location', e.target.value)}
                                  className="mt-0.5 w-full text-xs border border-teal-300 rounded-lg px-2.5 py-1.5 focus:outline-none focus:ring-1 focus:ring-teal-400 bg-white"
                                />
                              </div>
                              <div>
                                <label className="text-xs text-teal-600 font-medium">Est. cost ($)</label>
                                <input
                                  type="number"
                                  value={edit.cost ?? slot.estimated_cost_usd ?? ''}
                                  onChange={e => onSlotEdit(key, 'cost', e.target.value === '' ? null : Number(e.target.value))}
                                  className="mt-0.5 w-full text-xs border border-teal-300 rounded-lg px-2.5 py-1.5 focus:outline-none focus:ring-1 focus:ring-teal-400 bg-white"
                                />
                              </div>
                            </div>
                            <div>
                              <label className="text-xs text-teal-600 font-medium">Personal note</label>
                              <textarea
                                value={note}
                                onChange={e => onNoteChange(key, e.target.value)}
                                placeholder="Add your note…"
                                className="mt-0.5 w-full text-xs border border-teal-300 rounded-lg px-2.5 py-1.5 focus:outline-none focus:ring-1 focus:ring-teal-400 resize-none bg-white"
                                rows={2}
                              />
                            </div>
                            <button onClick={() => setEditingSlot(null)}
                              className="flex items-center gap-1 px-3 py-1 bg-teal-600 text-white rounded-full text-xs font-semibold hover:bg-teal-700">
                              <Check size={10}/> Done
                            </button>
                          </div>
                        ) : (
                          <>
                            <p data-activity className="text-sm font-medium text-gray-900">{activity}</p>
                            {location && <p className="text-sm text-gray-500 mt-0.5 flex items-center gap-1"><MapPin size={11}/>{location}</p>}
                            {slot.notes && !edit.activity && <p className="text-sm text-gray-400 mt-1 italic">{slot.notes}</p>}
                            {note && <p className="text-sm text-teal-600 mt-1 italic">📝 {note}</p>}
                          </>
                        )}
                      </div>

                      {/* Actions */}
                      {!isEditing && (
                        <div className="shrink-0 flex flex-col items-end gap-1.5">
                          {cost != null && <span className="text-sm text-gray-400">${cost}</span>}
                          <button type="button" aria-label={`Edit ${activity}`} onClick={() => { setEditingSlot(key); setOpenNote(null) }}
                            className={`flex items-center gap-1 px-2.5 py-1.5 rounded-full text-xs font-medium transition-colors ${(edit.activity || edit.location) ? 'bg-teal-100 text-teal-700' : 'bg-gray-100 text-gray-500 hover:bg-teal-100 hover:text-teal-700'}`}>
                            <PenLine size={10}/> {(edit.activity || edit.location) ? 'Edited' : 'Edit'}
                          </button>
                          <button type="button" aria-label={note ? `Edit note for ${activity}` : `Add note to ${activity}`}
                              onClick={() => { setOpenNote(isNoteOpen ? null : key); setEditingSlot(null) }}
                              className={`flex items-center gap-1 px-2.5 py-1.5 rounded-full text-xs font-medium transition-colors ${note ? 'bg-amber-100 text-amber-700' : 'bg-gray-100 text-gray-500 hover:bg-amber-100 hover:text-amber-700'}`}>
                              <MessageSquare size={10}/> {note ? 'Note ✓' : 'Note'}
                            </button>
                          {movable && (
                            <div>
                              <button type="button" ref={(el) => { moveButtons.current[key] = el }}
                                aria-label={`Move ${activity}`} aria-haspopup="menu" aria-expanded={menuOpen}
                                onClick={(e) => {
                                  setMenuAnchor(e.currentTarget.getBoundingClientRect())
                                  setMenuFor(menuOpen ? null : key)
                                }}
                                className={`flex items-center gap-1 px-2.5 py-1.5 rounded-full text-xs font-medium transition-colors ${menuOpen ? 'bg-teal-100 text-teal-700' : 'bg-gray-100 text-gray-500 hover:bg-teal-100 hover:text-teal-700'}`}>
                                <ArrowRightLeft size={10}/> Move
                              </button>
                              {menuOpen && (
                                <MoveMenu label={`Move ${activity}`} anchorRect={menuAnchor} anchorKey={key} getAnchor={getMoveButton}
                                  removeItem={removeItem} groups={menuGroups} onClose={() => closeMenu(key)} onDismiss={dismissMenu} />
                              )}
                            </div>
                          )}
                          <button type="button" aria-label={inPlan ? `Remove ${activity} from plan` : `Add ${activity} to plan`}
                            onClick={() => onSlotPlan(key, { key, day_number: day.day_number, time_of_day: slot.time_of_day, activity, location, estimated_cost_usd: cost })}
                            className={`flex items-center gap-1 px-2.5 py-1.5 rounded-full text-xs font-medium transition-colors ${
                              inPlan
                                ? 'bg-teal-600 text-white'
                                : 'bg-gray-100 text-gray-500 hover:bg-teal-100 hover:text-teal-700'
                            }`}>
                            {inPlan
                              ? <><Check size={10}/> In Plan</>
                              : <><Plus size={10}/> Plan</>
                            }
                          </button>
                        </div>
                      )}
                    </div>

                    {/* Inline note textarea when not in full edit mode */}
                    {isNoteOpen && !isEditing && (
                      <div className="mt-2 ml-23 pl-20">
                        <textarea
                          autoFocus
                          value={note}
                          onChange={e => onNoteChange(key, e.target.value)}
                          placeholder="Add your personal note…"
                          className="w-full text-xs border border-amber-300 rounded-lg px-2.5 py-2 focus:outline-none focus:ring-1 focus:ring-amber-400 resize-none bg-amber-50"
                          rows={2}
                        />
                      </div>
                    )}
                  </div>
                </Fragment>
              )
            })}
          </div>
        </div>
      ))}

      {/* Removed activities */}
      {removed.length > 0 && (
        <div data-removed-list className="border border-dashed border-gray-300 rounded-xl p-3">
          <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">Removed</p>
          <ul className="space-y-1.5">
            {removed.map(({ key, slot }) => {
              const name = activityName(key, slot.activity)
              const originalDay = data.days.find((d) => slotKey(d.day_number, slot.time_of_day) === key)
              const canRestore = restoreSlot(data, layout, key) !== layout
              return (
                <li key={key} className="flex items-center justify-between gap-2 text-sm">
                  <span className="text-gray-600 truncate">{name}</span>
                  {onRestoreSlot && (
                    <button type="button" disabled={!canRestore} aria-label={`Restore ${name}`}
                      title={canRestore ? undefined : `No free time left on Day ${originalDay?.day_number} — move or remove something there first`}
                      onClick={() => {
                        focusAfterRender.current = FOCUS_UNDO
                        onRestoreSlot(key)
                        setStatus(`Restored ${name}`)
                      }}
                      className="shrink-0 flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-medium bg-gray-100 text-gray-600 hover:bg-teal-100 hover:text-teal-700 disabled:opacity-40 disabled:hover:bg-gray-100 disabled:hover:text-gray-600">
                      <RotateCcw size={10}/> Restore
                    </button>
                  )}
                </li>
              )
            })}
          </ul>
        </div>
      )}

      {editable && <p aria-live="polite" className="sr-only">{status}</p>}
    </div>
  )
}
