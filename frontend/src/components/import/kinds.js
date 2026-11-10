import {
  Landmark, UtensilsCrossed, Wine, BedDouble, Ticket, Trees, ShoppingBag, Moon,
  CalendarDays, TramFront, MapPinned,
} from 'lucide-react'

// Each kind of imported place: its icon, its pin colour on the preview map,
// and the catalogue key of its readable label (namespace `search`). Pin colours are mid-dark so white numbers stay legible.
export const KINDS = {
  sight:     { icon: Landmark,        color: '#0f766e', labelKey: 'kinds.sight' },
  food:      { icon: UtensilsCrossed, color: '#c2410c', labelKey: 'kinds.food' },
  drink:     { icon: Wine,            color: '#be123c', labelKey: 'kinds.drink' },
  stay:      { icon: BedDouble,       color: '#475569', labelKey: 'kinds.stay' },
  activity:  { icon: Ticket,          color: '#0369a1', labelKey: 'kinds.activity' },
  nature:    { icon: Trees,           color: '#15803d', labelKey: 'kinds.nature' },
  shopping:  { icon: ShoppingBag,     color: '#be185d', labelKey: 'kinds.shopping' },
  nightlife: { icon: Moon,            color: '#4338ca', labelKey: 'kinds.nightlife' },
  event:     { icon: CalendarDays,    color: '#7e22ce', labelKey: 'kinds.event' },
  transport: { icon: TramFront,       color: '#57534e', labelKey: 'kinds.transport' },
  area:      { icon: MapPinned,       color: '#0e7490', labelKey: 'kinds.area' },
}

export const kindOf = (kind) => KINDS[kind] || KINDS.sight
