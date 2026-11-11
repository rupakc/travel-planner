// The onboarding quiz table and traveller-type classifier, ported from Android
// (rupakc/travel-planner-android: core/domain/.../profile/TravellerQuiz.kt and
// DefaultTravellerClassifier.kt, documented in docs/Onboarding-and-Traveller-Types.md).
// Every client must classify the same answers to the same type: change the
// table only together with Android (and iOS).
//
// Answers are `{questionId: [optionId, ...]}`. Unknown ids are ignored,
// duplicates count once, and a single-choice question counts only its first
// valid answer.

/** Order = tie-break order. ACCESSIBLE never scores; it is only ever a secondary. */
export const TRAVELLER_TYPES = [
  'BUDGET_BACKPACKER',
  'FAMILY',
  'LUXURY',
  'ADVENTURE',
  'CULTURE_FOODIE',
  'BUSINESS',
  'RELAXATION',
  'ACCESSIBLE',
]

/** Primary type when nothing scores: the broad "see and taste the place" traveller. */
export const DEFAULT_TYPE = 'CULTURE_FOODIE'

/** Secondary threshold: runner-up score ≥ 60 % of the primary's. */
export const SECONDARY_PERCENT = 60

const opt = (id, weights = {}, extra = {}) => ({ id, weights, ...extra })

/**
 * The six questions. Each option carries its classifier `weights` and what it
 * pre-fills in the server Preferences: `interestIds`, `budgetCategory`,
 * `accessibilityId`, `travellers` ({adults, children}), `addsInfant`; `pace`
 * is a search-form value with no Preferences field.
 */
export const QUESTIONS = [
  {
    id: 'companions',
    multiChoice: false,
    options: [
      opt('solo', { BUDGET_BACKPACKER: 2, ADVENTURE: 1 }, { travellers: { adults: 1, children: 0 } }),
      opt('partner', { RELAXATION: 2, LUXURY: 1, CULTURE_FOODIE: 1 }, { travellers: { adults: 2, children: 0 } }),
      opt('family_kids', { FAMILY: 4 }, { interestIds: ['family'], travellers: { adults: 2, children: 1 } }),
      opt('friends', { ADVENTURE: 2, BUDGET_BACKPACKER: 1 }, { travellers: { adults: 3, children: 0 } }),
      opt('work', { BUSINESS: 4 }, { travellers: { adults: 1, children: 0 } }),
    ],
  },
  {
    id: 'budget',
    multiChoice: false,
    options: [
      opt('shoestring', { BUDGET_BACKPACKER: 3 }, { budgetCategory: 'low' }),
      opt('mid_range', { CULTURE_FOODIE: 1, FAMILY: 1 }, { budgetCategory: 'medium' }),
      opt('comfort', { RELAXATION: 1, BUSINESS: 1 }, { budgetCategory: 'medium' }),
      opt('luxury', { LUXURY: 4 }, { budgetCategory: 'high' }),
    ],
  },
  {
    id: 'interests',
    multiChoice: true,
    options: [
      opt('food', { CULTURE_FOODIE: 2 }, { interestIds: ['food'] }),
      opt('history_culture', { CULTURE_FOODIE: 2 }, { interestIds: ['history', 'culture'] }),
      opt('nature', { ADVENTURE: 1, RELAXATION: 1 }, { interestIds: ['nature'] }),
      opt('adventure', { ADVENTURE: 2 }, { interestIds: ['adventure'] }),
      opt('nightlife', { BUDGET_BACKPACKER: 1 }, { interestIds: ['nightlife'] }),
      opt('shopping', { LUXURY: 1 }, { interestIds: ['shopping'] }),
      opt('art_museums', { CULTURE_FOODIE: 1 }, { interestIds: ['art'] }),
      opt('beaches', { RELAXATION: 2 }, { interestIds: ['nature', 'wellness'] }),
      opt('photography', { ADVENTURE: 1, CULTURE_FOODIE: 1 }, { interestIds: ['art'] }),
      opt('wellness', { RELAXATION: 1, LUXURY: 1 }, { interestIds: ['wellness'] }),
    ],
  },
  {
    id: 'pace',
    multiChoice: false,
    options: [
      opt('relaxed', { RELAXATION: 2, FAMILY: 1 }, { pace: 'relaxed' }),
      opt('balanced', { CULTURE_FOODIE: 1 }, { pace: 'balanced' }),
      opt('packed', { ADVENTURE: 1, BUSINESS: 1, BUDGET_BACKPACKER: 1 }, { pace: 'packed' }),
    ],
  },
  {
    id: 'planning',
    multiChoice: false,
    options: [
      opt('ahead_deals', { BUDGET_BACKPACKER: 1, FAMILY: 1 }),
      opt('loose', { CULTURE_FOODIE: 1, RELAXATION: 1 }),
      opt('spontaneous', { ADVENTURE: 1, BUDGET_BACKPACKER: 1 }),
    ],
  },
  {
    id: 'needs',
    multiChoice: true,
    options: [
      opt('wheelchair', {}, { accessibilityId: 'wheelchair' }),
      opt('visual_impairment', {}, { accessibilityId: 'visual_impairment' }),
      opt('hearing_impairment', {}, { accessibilityId: 'hearing_impairment' }),
      opt('cognitive_disability', {}, { accessibilityId: 'cognitive_disability' }),
      opt('infants', { FAMILY: 3 }, { addsInfant: true }),
      opt('dietary'),
    ],
  },
]

export const questionById = (id) => QUESTIONS.find((q) => q.id === id) || null

/** The valid options chosen for one question (deduplicated; first only for single choice). */
export function chosenFor(answers, questionId) {
  const question = questionById(questionId)
  const raw = answers && typeof answers === 'object' ? answers[questionId] : null
  if (!question || !Array.isArray(raw)) return []
  const picked = []
  for (const id of new Set(raw)) {
    const option = question.options.find((o) => o.id === id)
    if (option) picked.push(option)
  }
  return question.multiChoice ? picked : picked.slice(0, 1)
}

/** Every valid chosen option across the quiz, in question order. */
export const chosenAll = (answers) => QUESTIONS.flatMap((q) => chosenFor(answers, q.id))

/** True when any of the four accessibility needs was chosen (adds ACCESSIBLE). */
export const hasAccessibilityNeed = (answers) =>
  chosenFor(answers, 'needs').some((o) => o.accessibilityId)

/** Score per type (every type present, 0 when unscored). */
export function scores(answers) {
  const totals = Object.fromEntries(TRAVELLER_TYPES.map((t) => [t, 0]))
  for (const option of chosenAll(answers)) {
    for (const [type, weight] of Object.entries(option.weights)) totals[type] += weight
  }
  return totals
}

/** True when no answer scored (everything skipped, or only dietary/accessibility). */
export const nothingScored = (answers) => Object.values(scores(answers)).every((v) => v === 0)

/** -> {primary: TravellerType, secondary: TravellerType[]} */
export function classify(answers) {
  const totals = scores(answers)
  const ranked = TRAVELLER_TYPES
    .map((type, order) => ({ type, order, score: totals[type] }))
    .filter((e) => e.score > 0)
    .sort((a, b) => b.score - a.score || a.order - b.order)
  const primary = ranked[0]?.type ?? DEFAULT_TYPE
  const top = ranked[0]?.score ?? 0
  const second = ranked[1]
  const secondary = []
  // Integer check, as on Android: second × 100 ≥ primary × 60.
  if (second && second.score * 100 >= top * SECONDARY_PERCENT) secondary.push(second.type)
  if (hasAccessibilityNeed(answers) && primary !== 'ACCESSIBLE') secondary.push('ACCESSIBLE')
  return { primary, secondary: [...new Set(secondary)] }
}
