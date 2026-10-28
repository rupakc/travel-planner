const THEMES = {
  food: ['Foodie', 'Culinary', 'Gourmet', 'Tasty'],
  history: ['Historic', 'Ancient', 'Timeless', 'Heritage'],
  adventure: ['Wild', 'Epic', 'Daring', 'Thrilling'],
  culture: ['Cultural', 'Artistic', 'Vibrant', 'Soulful'],
  nature: ['Green', 'Natural', 'Serene', 'Wilderness'],
  shopping: ['Shopaholic', 'Boutique', 'Bazaar', 'Market'],
  nightlife: ['Midnight', 'Neon', 'After-Dark', 'Starlit'],
  wellness: ['Zen', 'Blissful', 'Peaceful', 'Tranquil'],
  art: ['Artsy', 'Creative', 'Gallery', 'Canvas'],
  family: ['Family', 'Joyful', 'Sunny', 'Playful'],
}

const TRIP_NOUNS = [
  'Adventure', 'Escape', 'Journey', 'Odyssey', 'Expedition',
  'Quest', 'Voyage', 'Getaway', 'Trail', 'Safari',
]

const SEASONAL = {
  spring: ['Blossom', 'Fresh', 'Springtime'],
  summer: ['Sunny', 'Sizzling', 'Tropical'],
  fall: ['Golden', 'Autumn', 'Amber'],
  winter: ['Frosty', 'Cozy', 'Snowbound'],
}

function getSeason(dateStr) {
  if (!dateStr) return null
  const month = new Date(dateStr).getMonth() + 1
  if (month >= 3 && month <= 5) return 'spring'
  if (month >= 6 && month <= 8) return 'summer'
  if (month >= 9 && month <= 11) return 'fall'
  return 'winter'
}

const pick = (arr) => arr[Math.floor(Math.random() * arr.length)]

export function generatePlanName(destination, interests = [], departureDate = null) {
  let adj
  const interest = interests?.[0]
  if (interest && THEMES[interest]) {
    adj = pick(THEMES[interest])
  } else {
    const season = getSeason(departureDate)
    adj = season ? pick(SEASONAL[season]) : pick(['Grand', 'Dreamy', 'Cosmic', 'Wanderlust'])
  }
  const noun = pick(TRIP_NOUNS)
  const dest = destination || 'Mystery'
  return `The ${adj} ${dest} ${noun}`
}

// Prices arrive from AI agents and may be strings or junk like "varies"
const price = (v) => {
  const n = Number(v)
  return Number.isFinite(n) && n > 0 ? n : 0
}

function hotelCost(hotel, searchData) {
  if (!hotel) return 0
  if (price(hotel.total_price_usd)) return price(hotel.total_price_usd)
  const nights =
    searchData?.return_date && searchData?.departure_date
      ? Math.max(1, (new Date(searchData.return_date) - new Date(searchData.departure_date)) / 86400000)
      : 7
  return price(hotel.price_per_night_usd) * nights
}

// Per-category split of the plan's cost, biggest first. Only categories with
// a numeric price are included — local transport has free-text fares only.
export function computePlanCostBreakdown(selections, searchData = null) {
  const parts = [
    {
      key: 'flights',
      label: 'Flights',
      amount: price(selections?.flight?.price_usd) +
        (selections?.flights || []).reduce((t, f) => t + price(f.price_usd), 0),
    },
    { key: 'hotel', label: 'Hotel', amount: hotelCost(selections?.hotel, searchData) },
    {
      key: 'activities',
      label: 'Activities',
      amount: (selections?.activities || []).reduce((t, a) => t + price(a.price_usd), 0),
    },
    { key: 'sim', label: 'SIM / eSIM', amount: price(selections?.sim?.price_usd) },
  ]
  return parts.filter((p) => p.amount > 0).sort((a, b) => b.amount - a.amount)
}

export function computePlanCost(selections, searchData = null) {
  return computePlanCostBreakdown(selections, searchData).reduce((t, p) => t + p.amount, 0)
}

export function getBudgetStatus(cost, budgetUsd) {
  if (!budgetUsd || cost <= 0) return null
  const diff = budgetUsd - cost
  if (diff >= 0) {
    return { status: 'under', amount: Math.round(diff), label: `$${Math.round(diff).toLocaleString()} under budget` }
  }
  return { status: 'over', amount: Math.round(Math.abs(diff)), label: `$${Math.round(Math.abs(diff)).toLocaleString()} over budget` }
}

// Identity check for per-leg flight selections (multi-city trips)
export function sameFlight(a, b) {
  if (!a || !b) return false
  return (
    (a.leg_index ?? null) === (b.leg_index ?? null) &&
    a.price_usd === b.price_usd &&
    (a.outbound?.airline ?? a.airline) === (b.outbound?.airline ?? b.airline) &&
    (a.outbound?.flight_number ?? a.flight_number) === (b.outbound?.flight_number ?? b.flight_number)
  )
}

export function countSelections(selections) {
  return (
    (selections?.flight ? 1 : 0) +
    (selections?.flights?.length || 0) +
    (selections?.hotel ? 1 : 0) +
    (selections?.activities?.length || 0) +
    (selections?.places_to_see?.length || 0) +
    (selections?.sim ? 1 : 0) +
    (selections?.getting_around?.length || 0) +
    (selections?.tips?.length || 0) +
    (selections?.events?.length || 0) +
    (selections?.itinerary_slots?.length || 0) +
    (selections?.packing_list ? 1 : 0)
  )
}

export const EMPTY_SELECTIONS = {
  flight: null,
  flights: [],
  hotel: null,
  activities: [],
  places_to_see: [],
  sim: null,
  tips: [],
  getting_around: [],
  events: [],
  itinerary_notes: {},
  itinerary_edits: {},
  itinerary_slots: [],
  packing_list: null,
}
