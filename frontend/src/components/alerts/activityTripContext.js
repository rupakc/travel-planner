import { createContext } from 'react'

/**
 * The trip around activity cards — `{ searchData, itinerary }` — so a
 * "Watch price" button knows the city, the travellers and the itinerary day
 * without threading props through every section. Null outside a trip page.
 */
export const ActivityTripContext = createContext(null)
