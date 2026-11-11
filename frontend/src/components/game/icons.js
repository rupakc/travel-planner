import { Award, Footprints, MailCheck, Map as MapIcon, Plane, Star, Trophy } from 'lucide-react'

// Catalogue badges name a lucide icon; only these ship, anything else is an Award.
const ICONS = {
  'mail-check': MailCheck,
  footprints: Footprints,
  map: MapIcon,
  plane: Plane,
  star: Star,
  trophy: Trophy,
}

export const badgeIcon = (name) => ICONS[name] || Award

export const TIER_CLASS = {
  bronze: 'bg-amber-100 text-amber-700',
  silver: 'bg-slate-200 text-slate-600',
  gold: 'bg-yellow-100 text-yellow-600',
}
