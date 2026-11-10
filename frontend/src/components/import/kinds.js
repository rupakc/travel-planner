import {
  Landmark, UtensilsCrossed, Wine, BedDouble, Ticket, Trees, ShoppingBag, Moon,
  CalendarDays, TramFront, MapPinned,
} from 'lucide-react'

// Each kind of imported place: its icon, its pin colour on the preview map,
// and a readable label. Pin colours are mid-dark so white numbers stay legible.
export const KINDS = {
  sight:     { icon: Landmark,        color: 'rgb(var(--c-teal-700))', label: 'Sight' },
  food:      { icon: UtensilsCrossed, color: 'rgb(var(--c-orange-700))', label: 'Food' },
  drink:     { icon: Wine,            color: 'rgb(var(--c-rose-700))', label: 'Drinks' },
  stay:      { icon: BedDouble,       color: 'rgb(var(--c-slate-600))', label: 'Stay' },
  activity:  { icon: Ticket,          color: 'rgb(var(--c-sky-700))', label: 'Activity' },
  nature:    { icon: Trees,           color: 'rgb(var(--c-green-700))', label: 'Nature' },
  shopping:  { icon: ShoppingBag,     color: 'rgb(var(--c-pink-700))', label: 'Shopping' },
  nightlife: { icon: Moon,            color: 'rgb(var(--c-indigo-700))', label: 'Nightlife' },
  event:     { icon: CalendarDays,    color: 'rgb(var(--c-purple-700))', label: 'Event' },
  transport: { icon: TramFront,       color: 'rgb(var(--c-stone-600))', label: 'Getting around' },
  area:      { icon: MapPinned,       color: 'rgb(var(--c-cyan-700))', label: 'Neighbourhood' },
}

export const kindOf = (kind) => KINDS[kind] || KINDS.sight
