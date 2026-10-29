// @vitest-environment node
import { describe, it, expect } from 'vitest'
import { buildBestValuePackage, applyPackage, isPackageApplied, packageConflicts } from './bestValuePackage'
import { computePlanCost, EMPTY_SELECTIONS } from './planHelpers'

const flight = (over = {}) => ({
  airline: 'TestAir',
  flight_number: 'TA1',
  price_usd: 500,
  source: 'live',
  outbound: { airline: 'TestAir', flight_number: 'TA1', stops: 0, duration_minutes: 600 },
  return: { stops: 0, duration_minutes: 600 },
  ...over,
})
const hotel = (over = {}) => ({
  name: 'Hotel A',
  star_rating: 3,
  price_per_night_usd: 100,
  review_score: 8,
  ...over,
})
const activity = (over = {}) => ({ name: 'Act', price_usd: 10, similarity_score: 0.4, city: 'Paris', ...over })
const tour = (over = {}) => ({ name: 'Tour', url: 'https://t/1', price_note: 'Free · tip-based', rating: 4.5, city: 'Paris', ...over })
const place = (over = {}) => ({ name: 'Place', admission_fee_usd: 0, rating: 4.5, city: 'Paris', ...over })
const sim = (over = {}) => ({ provider: 'P', plan_name: 'Plan', price_usd: 10, validity_days: 30, ...over })

const searchData = { departure_date: '2026-04-01', return_date: '2026-04-10', budget_usd: null }
const build = (results, sd = searchData) => buildBestValuePackage(results, sd)
const fl = (list) => ({ flights: { results: list } })
const itemsOf = (pkg, type) => pkg.items.filter((i) => i.type === type)

describe('flight pick', () => {
  it('prefers fewer stops within 15% of the cheapest fare', () => {
    const twoStop = flight({ flight_number: 'A', price_usd: 480, outbound: { airline: 'X', flight_number: 'A', stops: 2, duration_minutes: 900 } })
    const oneStop = flight({ flight_number: 'B', price_usd: 500, outbound: { airline: 'Y', flight_number: 'B', stops: 1, duration_minutes: 700 } })
    const pkg = build(fl([twoStop, oneStop]))
    expect(pkg.selections.flight).toBe(oneStop)
    expect(itemsOf(pkg, 'flight')[0].reason).toBe('Fewer stops for $20 more than the cheapest fare')
  })

  it('takes the cheapest fare when the direct one is outside 15%', () => {
    const cheap = flight({ flight_number: 'A', price_usd: 400, outbound: { airline: 'X', flight_number: 'A', stops: 2 } })
    const direct = flight({ flight_number: 'B', price_usd: 600 })
    const pkg = build(fl([direct, cheap]))
    expect(pkg.selections.flight).toBe(cheap)
    expect(itemsOf(pkg, 'flight')[0].reason).toBe('Cheapest fare')
  })

  it('drops estimates when a real fare exists, keeps them otherwise', () => {
    const est = flight({ flight_number: 'E', price_usd: 300, source: 'estimate' })
    const real = flight({ flight_number: 'R', price_usd: 500 })
    expect(build(fl([est, real])).selections.flight).toBe(real)
    expect(build(fl([est])).selections.flight).toBe(est)
  })

  it('ignores unknown prices and string prices are coerced', () => {
    const junk = flight({ flight_number: 'J', price_usd: 'varies' })
    const str = flight({ flight_number: 'S', price_usd: '450' })
    expect(build(fl([junk, str])).selections.flight).toBe(str)
  })

  it('breaks stop ties by duration then price', () => {
    const slow = flight({ flight_number: 'S', price_usd: 400, outbound: { airline: 'X', flight_number: 'S', stops: 0, duration_minutes: 900 } })
    const fast = flight({ flight_number: 'F', price_usd: 420, outbound: { airline: 'X', flight_number: 'F', stops: 0, duration_minutes: 500 } })
    expect(build(fl([slow, fast])).selections.flight).toBe(fast)
  })

  it('does not chase 5 minutes: $169 beats $183 when both are direct', () => {
    const mk = (n, price, out, ret) => flight({ flight_number: n, price_usd: price, outbound: { airline: 'X', flight_number: n, stops: 0, duration_minutes: out }, return: { stops: 0, duration_minutes: ret } })
    const cheap = mk('C', 169, 155, 165)
    const dear = mk('D', 183, 155, 160)
    const pkg = build(fl([dear, cheap]))
    expect(pkg.selections.flight).toBe(cheap)
    expect(itemsOf(pkg, 'flight')[0].reason).toBe('Cheapest fare')
  })

  it('takes a pricier same-stops fare that saves 90+ minutes', () => {
    const mk = (n, price, dur) => flight({ flight_number: n, price_usd: price, outbound: { airline: 'X', flight_number: n, stops: 1, duration_minutes: dur }, return: undefined })
    const slow = mk('S', 400, 600)
    const fast = mk('F', 430, 480)
    const pkg = build(fl([slow, fast]))
    expect(pkg.selections.flight).toBe(fast)
    expect(itemsOf(pkg, 'flight')[0].reason).toBe('Saves 2h of travel for $30 more than the cheapest fare')
  })

  it('ignores a fare that saves only 60 minutes or has unknown duration', () => {
    const mk = (n, price, dur) => flight({ flight_number: n, price_usd: price, outbound: { airline: 'X', flight_number: n, stops: 1, duration_minutes: dur }, return: undefined })
    const slow = mk('S', 400, 600)
    expect(build(fl([slow, mk('F', 430, 540)])).selections.flight).toBe(slow)
    expect(build(fl([slow, mk('U', 430, null)])).selections.flight).toBe(slow)
  })

  it('among several qualifying fares takes the shortest, then cheapest; formats h and m', () => {
    const mk = (n, price, dur) => flight({ flight_number: n, price_usd: price, outbound: { airline: 'X', flight_number: n, stops: 1, duration_minutes: dur }, return: undefined })
    const slow = mk('S', 400, 600)
    const a = mk('A', 410, 500)
    const b = mk('B', 430, 400)
    const pkg = build(fl([slow, a, b]))
    expect(pkg.selections.flight).toBe(b)
    expect(itemsOf(pkg, 'flight')[0].reason).toBe('Saves 3h 20m of travel for $30 more than the cheapest fare')
  })

  it('multi-city: one per leg into selections.flights', () => {
    const l0a = { leg_index: 0, price_usd: 100, outbound: { airline: 'A', flight_number: '1', stops: 1 } }
    const l0b = { leg_index: 0, price_usd: 110, outbound: { airline: 'B', flight_number: '2', stops: 0 } }
    const l1 = { leg_index: 1, price_usd: 80, outbound: { airline: 'C', flight_number: '3', stops: 0 } }
    const pkg = build({
      flights: { legs: [{ leg_index: 0, results: [l0a, l0b] }, { leg_index: 1, results: [l1] }, { leg_index: 2, results: [] }] },
    })
    expect(pkg.selections.flight).toBeNull()
    expect(pkg.selections.flights).toEqual([l0b, l1])
    expect(itemsOf(pkg, 'flights')).toHaveLength(2)
  })
})

describe('hotel pick', () => {
  it('prefers 3 star with the best review score', () => {
    const best = hotel({ name: 'Best', review_score: 9 })
    const pkg = build({ hotels: { results: [hotel({ name: 'Low', review_score: 7 }), best, hotel({ name: 'Four', star_rating: 4, review_score: 10 })] } })
    expect(pkg.selections.hotel).toBe(best)
    expect(itemsOf(pkg, 'hotel')[0].reason).toBe('Mid-range (3★), best-reviewed in its class')
  })

  it('falls back to 4 star, then any', () => {
    const four = hotel({ name: 'Four', star_rating: 4 })
    const five = hotel({ name: 'Five', star_rating: 5, review_score: 10 })
    expect(build({ hotels: { results: [five, four] } }).selections.hotel).toBe(four)
    expect(build({ hotels: { results: [five] } }).selections.hotel).toBe(five)
  })

  it('rounds string/float star ratings and puts unknown reviews last', () => {
    const unknown = hotel({ name: 'U', star_rating: '3', review_score: null })
    const known = hotel({ name: 'K', star_rating: 2.6, review_score: 6 })
    expect(build({ hotels: { results: [unknown, known] } }).selections.hotel).toBe(known)
  })

  it("ignores price_per_night_usd 'varies'", () => {
    const bad = hotel({ name: 'Bad', price_per_night_usd: 'varies', review_score: 10 })
    const good = hotel({ name: 'Good' })
    expect(build({ hotels: { results: [bad, good] } }).selections.hotel).toBe(good)
  })

  it('multi-city restricts to the first destination city', () => {
    const rome = hotel({ name: 'Rome', city: 'Rome', review_score: 10 })
    const paris = hotel({ name: 'Paris', city: 'Paris', review_score: 7 })
    const sd = { ...searchData, destinations: ['Paris', 'Rome'] }
    const pkg = build({ hotels: { results: [rome, paris] } }, sd)
    expect(pkg.selections.hotel).toBe(paris)
    expect(itemsOf(pkg, 'hotel')[0].reason).toContain('Paris')
  })
})

describe('budget fit', () => {
  const results = () => ({
    ...fl([flight({ price_usd: 500 })]),
    hotels: {
      results: [
        hotel({ name: 'Pricey', price_per_night_usd: 300, review_score: 9 }),
        hotel({ name: 'Cheap', star_rating: 2, price_per_night_usd: 50, review_score: 7.5 }),
        hotel({ name: 'Awful', star_rating: 1, price_per_night_usd: 20, review_score: 5 }),
      ],
    },
  })

  it('swaps in a cheaper, decently reviewed hotel when over budget', () => {
    const pkg = build(results(), { ...searchData, budget_usd: 1500 })
    expect(pkg.selections.hotel.name).toBe('Cheap')
    expect(itemsOf(pkg, 'hotel')[0].reason).toBe('Cheaper stay to fit your budget')
    expect(pkg.total).toBe(computePlanCost(pkg.selections, { ...searchData, budget_usd: 1500 }))
  })

  it('leaves the hotel alone when within budget or no budget', () => {
    expect(build(results(), { ...searchData, budget_usd: 99999 }).selections.hotel.name).toBe('Pricey')
    expect(build(results()).selections.hotel.name).toBe('Pricey')
  })

  it('never uses a cheaper hotel rated below 7', () => {
    const r = results()
    r.hotels.results = r.hotels.results.filter((h) => h.name !== 'Cheap')
    expect(build(r, { ...searchData, budget_usd: 100 }).selections.hotel.name).toBe('Pricey')
  })
})

describe('activities', () => {
  const acts = (list) => ({ ...fl([flight()]), activities: { results: list } })

  it('never picks unknown prices; zero price is Free', () => {
    const pkg = build(acts([activity({ name: 'N', price_usd: null }), activity({ name: 'Z', price_usd: 0 }), activity({ name: 'V', price_usd: 'varies' })]))
    expect(pkg.selections.activities.map((a) => a.name)).toEqual(['Z'])
    expect(itemsOf(pkg, 'activities')[0].reason.startsWith('Free')).toBe(true)
  })

  it('keeps the $30 floor for the cap, including string prices', () => {
    const list = [activity({ name: 'S', price_usd: '45' }), activity({ name: 'T', price_usd: 60 }), activity({ name: 'U', price_usd: 90 }), activity({ name: 'OK', price_usd: '12' })]
    const pkg = build(acts(list))
    expect(pkg.selections.activities.map((a) => a.name)).toEqual(['OK', 'S'])
    expect(itemsOf(pkg, 'activities')[0].reason).toBe('$12')
  })

  it('uses the per-city median as the cap when everything is pricey', () => {
    const prices = [39, 45, 48, 52, 55, 58, 59]
    const list = prices.map((p) => activity({ name: `P${p}`, price_usd: p, similarity_score: 0.1 }))
    const pkg = build(acts(list.slice().reverse()))
    // all eligible are 39..52; 2 per city cap picks the cheapest two (equal similarity)
    expect(pkg.selections.activities.map((a) => a.name)).toEqual(['P39', 'P45'])
    const four = build(acts(prices.map((p, i) => activity({ name: `P${p}`, price_usd: p, city: `C${i}` }))))
    expect(four.selections.activities.every((a) => a.price_usd <= 59)).toBe(true)
    const wide = build(acts(list.map((a) => ({ ...a, similarity_score: a.price_usd === 55 || a.price_usd === 59 ? 0.9 : 0.1 }))))
    expect(wide.selections.activities.map((a) => a.name).sort()).toEqual(['P39', 'P45'])
    expect(itemsOf(pkg, 'activities')[0].reason).toBe('$39 · below the typical price here')
  })

  it('adds the interest note for similarity >= 0.5', () => {
    const pkg = build(acts([activity({ price_usd: 12, similarity_score: 0.5 })]))
    expect(itemsOf(pkg, 'activities')[0].reason).toBe('$12 · matches your interests')
  })

  it('caps at 2 per city and 4 overall, best similarity first', () => {
    const list = []
    for (const city of ['A', 'B', 'C']) {
      for (let i = 0; i < 4; i++) list.push(activity({ name: `${city}${i}`, city, similarity_score: 0.9 - i * 0.1 }))
    }
    const pkg = build(acts(list))
    const names = pkg.selections.activities.map((a) => a.name)
    expect(names).toEqual(['A0', 'B0', 'C0', 'A1'])
    const one = build(acts(list.filter((a) => a.city === 'A')))
    expect(one.selections.activities.map((a) => a.name)).toEqual(['A0', 'A1'])
  })
})

describe('walking tours and places', () => {
  it('picks the top_pick tour per city', () => {
    const pick = tour({ name: 'Pick', url: 'u1', rating: 4.0, top_pick: true })
    const other = tour({ name: 'Other', url: 'u2', rating: 5 })
    const rome = tour({ name: 'Rome', url: 'u3', city: 'Rome' })
    const pkg = build({ ...fl([flight()]), walking_tours: { results: [other, pick, rome] } })
    expect(pkg.selections.walking_tours.map((t) => t.name).sort()).toEqual(['Pick', 'Rome'])
    expect(itemsOf(pkg, 'walking_tours')[0].reason).toBe('Free · tip-based')
  })

  it('places: only admission exactly 0, including the string "0"', () => {
    const pkg = build({
      ...fl([flight()]),
      places_to_see: {
        results: [
          place({ name: 'Zero' }),
          place({ name: 'StrZero', admission_fee_usd: '0' }),
          place({ name: 'Null', admission_fee_usd: null }),
          place({ name: 'Paid', admission_fee_usd: 12 }),
          place({ name: 'Blank', admission_fee_usd: '' }),
        ],
      },
    })
    expect(pkg.selections.places_to_see.map((p) => p.name).sort()).toEqual(['StrZero', 'Zero'])
    expect(itemsOf(pkg, 'places_to_see')[0].reason).toBe('Free entry')
  })

  it('places: top 2 per city, 4 overall', () => {
    const list = []
    for (const city of ['A', 'B', 'C']) for (let i = 0; i < 3; i++) list.push(place({ name: `${city}${i}`, city, rating: 5 - i * 0.1 }))
    const pkg = build({ ...fl([flight()]), places_to_see: { results: list } })
    expect(pkg.selections.places_to_see).toHaveLength(4)
    expect(pkg.selections.places_to_see.filter((p) => p.city === 'A')).toHaveLength(2)
  })
})

describe('sim pick', () => {
  const withSim = (plans) => build({ ...fl([flight()]), sim: { plans } })

  it('prefers a plan covering the trip over a cheaper short one', () => {
    const short = sim({ plan_name: 'Short', price_usd: 5, validity_days: 7 })
    const long = sim({ plan_name: 'Long', price_usd: 20, validity_days: 30 })
    const pkg = withSim([short, long])
    expect(pkg.selections.sim).toBe(long)
    expect(itemsOf(pkg, 'sim')[0].reason).toBe('Covers your 10-day trip')
  })

  it('takes the cheapest overall when none cover', () => {
    const a = sim({ plan_name: 'A', price_usd: 9, validity_days: 3 })
    const b = sim({ plan_name: 'B', price_usd: 5, validity_days: 7 })
    const pkg = withSim([a, b])
    expect(pkg.selections.sim).toBe(b)
    expect(itemsOf(pkg, 'sim')[0].reason).toBe('Cheapest plan')
  })

  it('ignores unpriced plans and treats missing dates as unknown trip length', () => {
    const free = sim({ plan_name: 'F', price_usd: 'n/a' })
    const ok = sim({ plan_name: 'O', price_usd: 8, validity_days: 3 })
    const pkg = buildBestValuePackage({ ...fl([flight()]), sim: { plans: [free, ok] } }, {})
    expect(pkg.selections.sim).toBe(ok)
    expect(itemsOf(pkg, 'sim')[0].reason).toBe('Cheapest plan')
  })
})

describe('package assembly', () => {
  it('still builds from the rest when a section errored', () => {
    const pkg = build({ ...fl([flight()]), hotels: { error: 'x' } })
    expect(pkg).not.toBeNull()
    expect(pkg.selections.hotel).toBeNull()
    expect(pkg.selections.flight).not.toBeNull()
  })

  it('returns null without a flight and a hotel', () => {
    expect(build({})).toBeNull()
    expect(build({ flights: { error: 'x' }, hotels: { error: 'y' }, activities: { results: [activity({ price_usd: 0 })] } })).toBeNull()
    expect(build(null)).toBeNull()
  })

  it('hotel alone is enough', () => {
    expect(build({ hotels: { results: [hotel()] } })).not.toBeNull()
  })

  it('selections only hold the package keys', () => {
    const pkg = build(fl([flight()]))
    expect(Object.keys(pkg.selections).sort()).toEqual(
      ['activities', 'flight', 'flights', 'hotel', 'places_to_see', 'sim', 'walking_tours'],
    )
  })

  it('total equals computePlanCost, is finite, and budget status matches', () => {
    const sd = { ...searchData, budget_usd: 5000 }
    const pkg = build({ ...fl([flight({ price_usd: '500' })]), hotels: { results: [hotel({ price_per_night_usd: 'varies' }), hotel({ name: 'H2' })] } }, sd)
    expect(pkg.total).toBe(computePlanCost(pkg.selections, sd))
    expect(Number.isFinite(pkg.total)).toBe(true)
    expect(pkg.budget.status).toBe('under')
  })
})

describe('applyPackage', () => {
  const full = () =>
    build({
      ...fl([flight()]),
      hotels: { results: [hotel({ name: 'Pkg Hotel' })] },
      activities: { results: [activity({ name: 'A1' }), activity({ name: 'A2' })] },
      walking_tours: { results: [tour()] },
      places_to_see: { results: [place()] },
      sim: { plans: [sim()] },
    })

  it('keeps existing activities, adds new without duplicates, replaces hotel, leaves other keys', () => {
    const pkg = full()
    const mine = activity({ name: 'Mine' })
    const before = {
      ...EMPTY_SELECTIONS,
      hotel: hotel({ name: 'Old' }),
      activities: [mine, activity({ name: 'A1' })],
      tips: [{ title: 't' }],
      itinerary_notes: { 1: 'n' },
    }
    const snapshot = JSON.parse(JSON.stringify(before))
    const after = applyPackage(before, pkg)
    expect(before).toEqual(snapshot)
    expect(after).not.toBe(before)
    expect(after.hotel.name).toBe('Pkg Hotel')
    expect(after.activities.map((a) => a.name)).toEqual(['Mine', 'A1', 'A2'])
    expect(after.tips).toEqual([{ title: 't' }])
    expect(after.itinerary_notes).toEqual({ 1: 'n' })
    expect(after.flight).toBe(pkg.selections.flight)
    expect(after.sim).toBe(pkg.selections.sim)
    expect(after.walking_tours).toHaveLength(1)
    expect(after.places_to_see).toHaveLength(1)
  })

  it('is idempotent', () => {
    const pkg = full()
    const once = applyPackage(EMPTY_SELECTIONS, pkg)
    const twice = applyPackage(once, pkg)
    expect(countOf(twice)).toBe(countOf(once))
  })

  it('multi-city replaces only covered legs', () => {
    const mk = (i, p, a) => ({ leg_index: i, price_usd: p, outbound: { airline: a, flight_number: 'X', stops: 0 } })
    const pkg = build({ flights: { legs: [{ leg_index: 0, results: [mk(0, 100, 'New')] }] } })
    const mine1 = mk(1, 90, 'Mine1')
    const old0 = mk(0, 300, 'Old0')
    const after = applyPackage({ ...EMPTY_SELECTIONS, flights: [old0, mine1] }, pkg)
    expect(after.flights.map((f) => f.outbound.airline)).toEqual(['New', 'Mine1'])
  })
})

const countOf = (s) => s.activities.length + s.walking_tours.length + s.places_to_see.length

describe('isPackageApplied', () => {
  const pkg = () =>
    build({ ...fl([flight()]), hotels: { results: [hotel()] }, activities: { results: [activity({ name: 'A1' })] }, sim: { plans: [sim()] } })

  it('true right after apply, false after removing one item', () => {
    const p = pkg()
    expect(isPackageApplied(EMPTY_SELECTIONS, p)).toBe(false)
    const applied = applyPackage(EMPTY_SELECTIONS, p)
    expect(isPackageApplied(applied, p)).toBe(true)
    expect(isPackageApplied({ ...applied, activities: [] }, p)).toBe(false)
    expect(isPackageApplied({ ...applied, sim: null }, p)).toBe(false)
  })

  it('multi-city requires every covered leg', () => {
    const mk = (i) => ({ leg_index: i, price_usd: 100 + i, outbound: { airline: 'A', flight_number: String(i), stops: 0 } })
    const p = build({ flights: { legs: [{ leg_index: 0, results: [mk(0)] }, { leg_index: 1, results: [mk(1)] }] } })
    const applied = applyPackage(EMPTY_SELECTIONS, p)
    expect(isPackageApplied(applied, p)).toBe(true)
    expect(isPackageApplied({ ...applied, flights: [mk(0)] }, p)).toBe(false)
  })
})

describe('packageConflicts', () => {
  const p = build({ ...fl([flight()]), hotels: { results: [hotel({ name: 'Mine' })] }, sim: { plans: [sim()] } })

  it('reports a different hotel', () => {
    expect(packageConflicts({ ...EMPTY_SELECTIONS, hotel: hotel({ name: 'Other' }) }, p)).toEqual(['hotel'])
  })

  it('is empty for nothing or the same items', () => {
    expect(packageConflicts(EMPTY_SELECTIONS, p)).toEqual([])
    expect(packageConflicts({ ...EMPTY_SELECTIONS, hotel: hotel({ name: 'Mine' }) }, p)).toEqual([])
  })

  it('reports flight and SIM too', () => {
    const sel = { ...EMPTY_SELECTIONS, flight: flight({ price_usd: 999 }), sim: sim({ plan_name: 'Else' }) }
    expect(packageConflicts(sel, p)).toEqual(['flight', 'SIM'])
  })
})

describe('fix round 1', () => {
  it('whitespace and array prices are unknown, not free', () => {
    const acts = [activity({ name: 'W', price_usd: ' ' }), activity({ name: 'Arr', price_usd: [] })]
    const pkg = build({ ...fl([flight()]), activities: { results: acts } })
    expect(pkg.selections.activities).toEqual([])
    const f = build(fl([flight({ price_usd: ' ' })]))
    expect(f).toBeNull()
  })

  it('nameless activities are skipped and package duplicates are applied once', () => {
    const pkg = build({ ...fl([flight()]), activities: { results: [activity({ name: undefined }), activity({ name: 'D' }), activity({ name: 'D' })] } })
    expect(pkg.selections.activities.map((a) => a.name)).toEqual(['D', 'D'])
    const applied = applyPackage(EMPTY_SELECTIONS, pkg)
    expect(applied.activities).toHaveLength(1)
    expect(isPackageApplied(applied, pkg)).toBe(true)
  })

  it('hotel reason only says Mid-range for 3 stars', () => {
    const four = build({ hotels: { results: [hotel({ star_rating: 4 })] } })
    expect(itemsOf(four, 'hotel')[0].reason).toBe('4★, best-reviewed in its class')
    const multi = build({ hotels: { results: [hotel({ star_rating: 4, city: 'Rome' })] } }, { ...searchData, destinations: ['Rome', 'X'] })
    expect(itemsOf(multi, 'hotel')[0].reason).toBe('4★, best-reviewed in its class · Rome')
  })

  it('a sub-50-cent premium reads Cheapest fare', () => {
    const a = flight({ flight_number: 'A', price_usd: 100, outbound: { airline: 'X', flight_number: 'A', stops: 1 } })
    const b = flight({ flight_number: 'B', price_usd: 100.3, outbound: { airline: 'Y', flight_number: 'B', stops: 0 } })
    const pkg = build(fl([a, b]))
    expect(pkg.selections.flight).toBe(b)
    expect(itemsOf(pkg, 'flight')[0].reason).toBe('Cheapest fare')
  })

  it('SIM plans lacking identity never compare equal', () => {
    const p = build({ ...fl([flight()]), sim: { plans: [{ price_usd: 5 }] } })
    expect(packageConflicts({ ...EMPTY_SELECTIONS, sim: { price_usd: 9 } }, p)).toEqual(['SIM'])
    expect(isPackageApplied({ ...EMPTY_SELECTIONS, flight: p.selections.flight, sim: { price_usd: 5 } }, p)).toBe(false)
  })

  it('applyPackage tolerates null selections', () => {
    const l = { leg_index: 0, price_usd: 80, outbound: { airline: 'C', flight_number: '3', stops: 0 } }
    const pkg = build({ flights: { legs: [{ leg_index: 0, results: [l] }], results: [l] }, activities: { results: [activity({ name: 'N' })] } })
    expect(applyPackage(null, pkg).flights).toEqual([l])
  })

  it('non-array leg.results does not throw', () => {
    const l1 = { leg_index: 1, price_usd: 80, outbound: { airline: 'C', flight_number: '3', stops: 0 } }
    const pkg = build({ flights: { legs: [{ leg_index: 0, results: 'oops' }, { leg_index: 1, results: [l1] }] } })
    expect(pkg.selections.flights).toEqual([l1])
  })
})

describe('multi-city first stop matching', () => {
  const lis = hotel({ name: 'Lis', city: 'Lisbon', review_score: 7 })
  const opo = hotel({ name: 'Opo', city: 'Porto, Portugal', review_score: 10 })
  const sd = (destinations) => ({ ...searchData, destinations })

  it('(a) IATA destinations: uses flights.legs[0].to', () => {
    const results = {
      flights: { legs: [{ leg_index: 0, to: 'Lisbon, Portugal', results: [flight({ leg_index: 0 })] }] },
      hotels: { results: [opo, lis] },
    }
    const pkg = build(results, sd(['LIS', 'OPO']))
    expect(pkg.selections.hotel).toBe(lis)
    expect(itemsOf(pkg, 'hotel')[0].reason).toContain('Lisbon')
  })

  it('(b) names match by first comma segment', () => {
    const l = hotel({ name: 'L', city: 'Lisbon, Portugal', review_score: 6 })
    const pkg = build({ hotels: { results: [opo, l] } }, sd(['Lisbon', 'Porto']))
    expect(pkg.selections.hotel).toBe(l)
  })

  it('(c) codes with no legs: first city-tagged hotel decides', () => {
    const pkg = build({ hotels: { results: [lis, opo, hotel({ name: 'Lis2', city: 'lisbon', review_score: 9 })] } }, sd(['LIS', 'OPO']))
    expect(pkg.selections.hotel.name).toBe('Lis2')
  })

  it('(d) budget swap stays in the first city', () => {
    const cheapOpo = hotel({ name: 'CheapOpo', city: 'Porto', price_per_night_usd: 10, review_score: 9 })
    const cheapLis = hotel({ name: 'CheapLis', city: 'Lisbon', star_rating: 2, price_per_night_usd: 40, review_score: 8 })
    const results = {
      flights: { legs: [{ leg_index: 0, to: 'Lisbon', results: [flight({ leg_index: 0, price_usd: 500 })] }] },
      hotels: { results: [hotel({ name: 'BigLis', city: 'Lisbon', price_per_night_usd: 300 }), cheapOpo, cheapLis] },
    }
    const pkg = build(results, { ...sd(['LIS', 'OPO']), budget_usd: 1000 })
    expect(pkg.selections.hotel.name).toBe('CheapLis')
  })
})
