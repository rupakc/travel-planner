// Alerts page: which card renders a price watch of each kind.
// Add a kind by creating its card in this folder and one line below, e.g.
//   import HotelWatchCard from './HotelWatchCard'   →   hotel: HotelWatchCard,
// A card gets the props documented on PriceWatchCard (it can wrap it and
// pass Details / openLabel / unitLabel). Fare watches keep ../WatchCard.
import PriceWatchCard from './PriceWatchCard'
import TripWatchCard from './TripWatchCard'

export const PRICE_CARDS = {
  trip: TripWatchCard,
}

export function cardFor(kind) {
  return PRICE_CARDS[kind] || PriceWatchCard
}
