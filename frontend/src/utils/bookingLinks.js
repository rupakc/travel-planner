/**
 * bookingLinks.js
 * Deep-link generators for external booking and search services.
 */

/**
 * Extract a 3-letter IATA airport code from a string such as "JFK" or "New York (JFK)".
 * Returns null when no code is found.
 */
function extractIATA(value) {
  if (!value) return null;
  const match = String(value).match(/\b([A-Z]{3})\b/);
  return match ? match[1] : null;
}

/**
 * Format a date value as YYYYMMDD for Skyscanner deep links.
 * Accepts Date objects, ISO strings, or already-formatted YYYYMMDD strings.
 */
function formatSkyscannerDate(date) {
  if (!date) return '';
  const d = new Date(date);
  if (isNaN(d.getTime())) return String(date).replace(/-/g, '');
  const yyyy = d.getFullYear();
  const mm = String(d.getMonth() + 1).padStart(2, '0');
  const dd = String(d.getDate()).padStart(2, '0');
  return `${yyyy}${mm}${dd}`;
}

/**
 * Generate a Skyscanner deep link for a flight search.
 * Falls back to Google Flights when IATA codes cannot be parsed.
 *
 * @param {object} params
 * @param {string} params.origin           - Origin airport/city string, e.g. "JFK" or "New York (JFK)"
 * @param {string} params.destination      - Destination airport/city string
 * @param {string|Date} params.departureDate
 * @param {string|Date} [params.returnDate]
 * @param {number} [params.adults=1]
 * @returns {string} URL
 */
export function flightDeepLink({ origin, destination, departureDate, returnDate, adults = 1 }) {
  const orig = extractIATA(origin);
  const dest = extractIATA(destination);

  if (!orig || !dest) {
    // Fallback: Google Flights
    const params = new URLSearchParams();
    if (origin) params.set('origin', origin);
    if (destination) params.set('dest', destination);
    if (departureDate) params.set('date', String(departureDate).slice(0, 10));
    if (returnDate) params.set('return', String(returnDate).slice(0, 10));
    if (adults && adults > 1) params.set('adults', String(adults));
    return `https://www.google.com/flights?${params.toString()}`;
  }

  const dep = formatSkyscannerDate(departureDate);
  const ret = returnDate ? formatSkyscannerDate(returnDate) : '';
  const n = adults && Number.isInteger(adults) && adults > 0 ? adults : 1;

  if (ret) {
    return `https://www.skyscanner.net/transport/flights/${orig}/${dest}/${dep}/${ret}/?adults=${n}`;
  }
  return `https://www.skyscanner.net/transport/flights/${orig}/${dest}/${dep}/?adults=${n}`;
}

/**
 * Generate a Booking.com deep link for a hotel search.
 *
 * @param {object} params
 * @param {string} params.hotelName
 * @param {string} params.destination
 * @param {string|Date} params.checkIn
 * @param {string|Date} params.checkOut
 * @param {number} [params.guests=1]
 * @returns {string} URL
 */
export function hotelDeepLink({ hotelName, destination, checkIn, checkOut, guests = 1 }) {
  const base = 'https://www.booking.com/search.html';
  const params = new URLSearchParams();

  const query = [hotelName, destination].filter(Boolean).join(' ');
  if (query) params.set('ss', query);

  if (checkIn) {
    const d = new Date(checkIn);
    if (!isNaN(d.getTime())) {
      params.set('checkin_year', String(d.getFullYear()));
      params.set('checkin_month', String(d.getMonth() + 1));
      params.set('checkin_monthday', String(d.getDate()));
    }
  }

  if (checkOut) {
    const d = new Date(checkOut);
    if (!isNaN(d.getTime())) {
      params.set('checkout_year', String(d.getFullYear()));
      params.set('checkout_month', String(d.getMonth() + 1));
      params.set('checkout_monthday', String(d.getDate()));
    }
  }

  const g = guests && Number.isInteger(guests) && guests > 0 ? guests : 1;
  params.set('group_adults', String(g));

  return `${base}?${params.toString()}`;
}

/**
 * Generate a Viator search URL for an activity.
 *
 * @param {object} params
 * @param {string} params.activityName
 * @param {string} params.destination
 * @returns {string} URL
 */
export function activityDeepLink({ activityName, destination }) {
  const query = [activityName, destination].filter(Boolean).join(' ');
  const params = new URLSearchParams({ text: query || '' });
  return `https://www.viator.com/search?${params.toString()}`;
}

/**
 * Generate a Google Maps search URL for a restaurant.
 *
 * @param {object} params
 * @param {string} params.restaurantName
 * @param {string} params.destination
 * @returns {string} URL
 */
export function restaurantDeepLink({ restaurantName, destination }) {
  const query = [restaurantName, destination].filter(Boolean).join(' ');
  const params = new URLSearchParams({ q: query || '' });
  return `https://www.google.com/maps/search/?api=1&${params.toString()}`;
}
