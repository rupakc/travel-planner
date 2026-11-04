import {
  Landmark, UtensilsCrossed, Wine, BedDouble, Ticket, Trees, ShoppingBag, Moon,
  CalendarDays, TramFront, MapPinned,
} from 'lucide-react'

// Each kind of imported place: its icon, its pin colour on the preview map,
// and a readable label. Pin colours are mid-dark so white numbers stay legible.
export const KINDS = {
  sight:     { icon: Landmark,        color: '#0f766e', label: 'Sight' },
  food:      { icon: UtensilsCrossed, color: '#c2410c', label: 'Food' },
  drink:     { icon: Wine,            color: '#be123c', label: 'Drinks' },
  stay:      { icon: BedDouble,       color: '#475569', label: 'Stay' },
  activity:  { icon: Ticket,          color: '#0369a1', label: 'Activity' },
  nature:    { icon: Trees,           color: '#15803d', label: 'Nature' },
  shopping:  { icon: ShoppingBag,     color: '#be185d', label: 'Shopping' },
  nightlife: { icon: Moon,            color: '#4338ca', label: 'Nightlife' },
  event:     { icon: CalendarDays,    color: '#7e22ce', label: 'Event' },
  transport: { icon: TramFront,       color: '#57534e', label: 'Getting around' },
  area:      { icon: MapPinned,       color: '#0e7490', label: 'Neighbourhood' },
}

export const kindOf = (kind) => KINDS[kind] || KINDS.sight
