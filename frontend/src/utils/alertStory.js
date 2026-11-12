// Pure helpers for the price story (docs/Alerts-API.md). Stubs: filled in by a
// later task, against backend/tests/fixtures/alerts/story_cases.json.

/** 'great' | 'good' | 'typical' | 'high' | null for a price against {low, high}. */
export function verdictFor() { return null }

/** {code, params} for a PriceStory, first matching rule wins. */
export function adviceFor() { return null }

/** How many of `points` ({price}) are at or below `target`. */
export function countAtOrBelow() { return 0 }

/** Whole days between an ISO time and `now`, or null. */
export function checkedDaysAgo() { return null }
