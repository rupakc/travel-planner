import {
  Landmark, UtensilsCrossed, Wine, BedDouble, Ticket, Trees, ShoppingBag, Moon,
  CalendarDays, TramFront, MapPinned,
} from 'lucide-react'

// Each kind of imported place: its icon, its pin colour on the preview map,
// and the catalogue key of its readable label (namespace `search`). Pin colours are mid-dark so white numbers stay legible.
export const KINDS = {
  sight:     { icon: Landmark,        color: 'rgb(var(--c-teal-700))', labelKey: 'kinds.sight' },
  food:      { icon: UtensilsCrossed, color: 'rgb(var(--c-orange-700))', labelKey: 'kinds.food' },
  drink:     { icon: Wine,            color: 'rgb(var(--c-rose-700))', labelKey: 'kinds.drink' },
  stay:      { icon: BedDouble,       color: 'rgb(var(--c-slate-600))', labelKey: 'kinds.stay' },
  activity:  { icon: Ticket,          color: 'rgb(var(--c-sky-700))', labelKey: 'kinds.activity' },
  nature:    { icon: Trees,           color: 'rgb(var(--c-green-700))', labelKey: 'kinds.nature' },
  shopping:  { icon: ShoppingBag,     color: 'rgb(var(--c-pink-700))', labelKey: 'kinds.shopping' },
  nightlife: { icon: Moon,            color: 'rgb(var(--c-indigo-700))', labelKey: 'kinds.nightlife' },
  event:     { icon: CalendarDays,    color: 'rgb(var(--c-purple-700))', labelKey: 'kinds.event' },
  transport: { icon: TramFront,       color: 'rgb(var(--c-stone-600))', labelKey: 'kinds.transport' },
  area:      { icon: MapPinned,       color: 'rgb(var(--c-cyan-700))', labelKey: 'kinds.area' },
}

export const kindOf = (kind) => KINDS[kind] || KINDS.sight
