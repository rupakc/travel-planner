import { useState } from 'react'
import { DollarSign, Check, MapPin, PenLine, MessageSquare, Plus } from 'lucide-react'
import TripMap from './TripMap'

export default function ItinerarySection({ data, selections, onNoteChange, onSlotEdit, onSlotPlan }) {
  const [editingSlot, setEditingSlot] = useState(null) // key of slot being edited
  const [openNote,    setOpenNote]    = useState(null)

  if (!data?.days?.length) return <div className="p-4 text-sm text-gray-500">No itinerary available</div>

  const slotIcons = { morning: '🌅', afternoon: '☀️', evening: '🌙' }

  return (
    <div className="p-4 space-y-4">
      {/* Map at the top */}
      <TripMap days={data.days} />

      {/* Header row */}
      <div className="flex items-center justify-between">
        {data.total_estimated_cost_usd > 0 && (
          <div className="flex items-center gap-2 p-2.5 bg-teal-50 rounded-lg border border-teal-200 text-sm">
            <DollarSign size={13} className="text-teal-600" />
            <span className="text-teal-800 font-medium">Est. itinerary cost: ${data.total_estimated_cost_usd.toLocaleString()}</span>
          </div>
        )}
        {data.source === 'template' && (
          <span className="text-xs text-amber-600 bg-amber-50 border border-amber-200 px-2 py-1 rounded-full">Auto-generated — click any slot to edit</span>
        )}
      </div>

      {data.days.map((day) => (
        <div key={day.day_number} className="border border-gray-200 rounded-xl overflow-hidden">
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

          {/* Slots */}
          <div className="divide-y divide-gray-100">
            {day.slots?.map((slot, j) => {
              const key = `${day.day_number}-${slot.time_of_day}`
              const edit  = selections.itinerary_edits?.[key] || {}
              const note  = selections.itinerary_notes?.[key] || ''
              const isEditing  = editingSlot === key
              const isNoteOpen = openNote === key

              // Merge saved edits over original slot data
              const activity = edit.activity  ?? slot.activity
              const location = edit.location  ?? slot.location
              const cost     = edit.cost      ?? slot.estimated_cost_usd

              return (
                <div key={j} className={`px-4 py-3 transition-colors ${isEditing ? 'bg-teal-50' : 'hover:bg-gray-50'}`}>
                  <div className="flex gap-3">
                    {/* Time icon */}
                    <div className="w-20 shrink-0 text-sm text-gray-500 font-medium capitalize flex items-center gap-1">
                      <span>{slotIcons[slot.time_of_day]}</span>
                      <span>{slot.time_of_day}</span>
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
                          <p className="text-sm font-medium text-gray-900">{activity}</p>
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
                        <button onClick={() => { setEditingSlot(key); setOpenNote(null) }}
                          className={`flex items-center gap-1 px-2.5 py-1.5 rounded-full text-xs font-medium transition-colors ${(edit.activity || edit.location) ? 'bg-teal-100 text-teal-700' : 'bg-gray-100 text-gray-500 hover:bg-teal-100 hover:text-teal-700'}`}>
                          <PenLine size={10}/> {(edit.activity || edit.location) ? 'Edited' : 'Edit'}
                        </button>
                        <button onClick={() => { setOpenNote(isNoteOpen ? null : key); setEditingSlot(null) }}
                            className={`flex items-center gap-1 px-2.5 py-1.5 rounded-full text-xs font-medium transition-colors ${note ? 'bg-amber-100 text-amber-700' : 'bg-gray-100 text-gray-500 hover:bg-amber-100 hover:text-amber-700'}`}>
                            <MessageSquare size={10}/> {note ? 'Note ✓' : 'Note'}
                          </button>
                        <button onClick={() => onSlotPlan(key, { key, day_number: day.day_number, time_of_day: slot.time_of_day, activity, location, estimated_cost_usd: cost })}
                          className={`flex items-center gap-1 px-2.5 py-1.5 rounded-full text-xs font-medium transition-colors ${
                            selections.itinerary_slots?.some(s => s.key === key)
                              ? 'bg-teal-600 text-white'
                              : 'bg-gray-100 text-gray-500 hover:bg-teal-100 hover:text-teal-700'
                          }`}>
                          {selections.itinerary_slots?.some(s => s.key === key)
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
              )
            })}
          </div>
        </div>
      ))}
    </div>
  )
}
