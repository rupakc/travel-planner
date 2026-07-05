// Multi-city: agents are told to follow the journey order but LLM output is
// not guaranteed — stable-sort every city-tagged list so items always appear
// in the exact stop order the user entered.
//
// Kept as a pure util (no component imports) so nothing here can ever be
// shadowed by an icon import — `new Map` below must be the global Map.
const CITY_LIST_FIELDS = ['results', 'hotels', 'places', 'events', 'options', 'plans']

export function orderSectionByCity(data, destinations) {
  if (!destinations || destinations.length < 2 || !data || typeof data !== 'object' || Array.isArray(data)) return data
  const order = new Map(destinations.map((c, i) => [c.split(',')[0].trim().toLowerCase(), i]))
  const cityIdx = item => {
    const raw = Array.isArray(item?.city) ? item.city[0] : item?.city
    const c = (raw || '').split(',')[0].trim().toLowerCase()
    return order.has(c) ? order.get(c) : destinations.length
  }
  const out = { ...data }
  for (const field of CITY_LIST_FIELDS) {
    if (Array.isArray(out[field]) && out[field].some(it => it?.city)) {
      out[field] = [...out[field]].sort((a, b) => cityIdx(a) - cityIdx(b))
    }
  }
  return out
}
