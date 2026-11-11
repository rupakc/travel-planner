// Ported case by case from Android
// core/domain/src/test/.../profile/TravellerClassifierTest.kt
// (rupakc/travel-planner-android). Keep both in step: the classifier must
// give the same type on every client.
import { describe, it, expect } from 'vitest'
import {
  QUESTIONS, TRAVELLER_TYPES, DEFAULT_TYPE, classify as classifyMap, scores,
} from './travellerQuiz'

const COMPANIONS = 'companions'
const BUDGET = 'budget'
const INTERESTS = 'interests'
const PACE = 'pace'
const PLANNING = 'planning'
const NEEDS = 'needs'

const classify = (...pairs) => classifyMap(Object.fromEntries(pairs))
const nonZero = (s) => Object.fromEntries(Object.entries(s).filter(([, v]) => v > 0))
const result = (primary, secondary) => ({ primary, secondary })

describe('travellerQuiz classifier (Android TravellerClassifierTest)', () => {
  it('quiz has six questions with unique ids and options', () => {
    expect(QUESTIONS.map((q) => q.id)).toEqual([COMPANIONS, BUDGET, INTERESTS, PACE, PLANNING, NEEDS])
    for (const q of QUESTIONS) expect(new Set(q.options.map((o) => o.id)).size).toBe(q.options.length)
    expect(QUESTIONS.filter((q) => q.multiChoice).map((q) => q.id)).toEqual([INTERESTS, NEEDS])
  })

  it('every scored type is reachable as primary', () => {
    const cases = {
      BUDGET_BACKPACKER: classify([COMPANIONS, ['solo']], [BUDGET, ['shoestring']]),
      FAMILY: classify([COMPANIONS, ['family_kids']]),
      LUXURY: classify([BUDGET, ['luxury']]),
      ADVENTURE: classify([INTERESTS, ['adventure']]),
      CULTURE_FOODIE: classify([INTERESTS, ['food']]),
      BUSINESS: classify([COMPANIONS, ['work']]),
      RELAXATION: classify([INTERESTS, ['beaches']]),
    }
    for (const [type, r] of Object.entries(cases)) expect(r.primary).toBe(type)
    // Together with ACCESSIBLE (secondary-only) that covers every type.
    expect(Object.keys(cases).sort()).toEqual(TRAVELLER_TYPES.filter((t) => t !== 'ACCESSIBLE').sort())
  })

  it('accessible is reachable and added as a secondary for each accessibility need', () => {
    for (const need of ['wheelchair', 'visual_impairment', 'hearing_impairment', 'cognitive_disability']) {
      const r = classify([COMPANIONS, ['work']], [NEEDS, [need]])
      expect(r.primary).toBe('BUSINESS')
      expect(r.secondary).toEqual(['ACCESSIBLE'])
    }
  })

  it('accessible comes after the scored secondary and never replaces types', () => {
    const r = classify([PACE, ['packed']], [NEEDS, ['wheelchair']])
    expect(r.primary).toBe('BUDGET_BACKPACKER')
    expect(r.secondary).toEqual(['ADVENTURE', 'ACCESSIBLE'])
  })

  it('infants and dietary needs do not add accessible', () => {
    const r = classify([NEEDS, ['infants', 'dietary']])
    expect(r.primary).toBe('FAMILY')
    expect(r.secondary).toEqual([])
  })

  it('ties are broken by the fixed type order', () => {
    // packed = ADVENTURE 1, BUSINESS 1, BUDGET_BACKPACKER 1
    const r = classify([PACE, ['packed']])
    expect(r.primary).toBe('BUDGET_BACKPACKER')
    expect(r.secondary).toEqual(['ADVENTURE'])
    // loose = CULTURE_FOODIE 1, RELAXATION 1
    expect(classify([PLANNING, ['loose']])).toEqual(result('CULTURE_FOODIE', ['RELAXATION']))
  })

  it('secondary needs at least 60 percent of the primary score', () => {
    // LUXURY 5, RELAXATION 3, CULTURE_FOODIE 1 → 3/5 = 60 % → secondary
    const atThreshold = { [BUDGET]: ['luxury'], [INTERESTS]: ['shopping', 'beaches'], [PLANNING]: ['loose'] }
    expect(nonZero(scores(atThreshold))).toEqual({ LUXURY: 5, RELAXATION: 3, CULTURE_FOODIE: 1 })
    expect(classifyMap(atThreshold)).toEqual(result('LUXURY', ['RELAXATION']))

    // LUXURY 5, RELAXATION 2 → 40 % → none
    const below = classify([BUDGET, ['luxury']], [INTERESTS, ['shopping', 'beaches']])
    expect(below).toEqual(result('LUXURY', []))
  })

  it('only one scored secondary even when several qualify', () => {
    // partner: RELAXATION 2, LUXURY 1, CULTURE_FOODIE 1 → plus food: CULTURE_FOODIE 3 → CF 3, R 2, L 1
    const r = classify([COMPANIONS, ['partner']], [INTERESTS, ['food']])
    expect(r.primary).toBe('CULTURE_FOODIE')
    expect(r.secondary).toEqual(['RELAXATION'])
  })

  it('empty or skipped answers give the default type', () => {
    const expected = result(DEFAULT_TYPE, [])
    expect(DEFAULT_TYPE).toBe('CULTURE_FOODIE')
    expect(classifyMap({})).toEqual(expected)
    expect(classify([COMPANIONS, []], [INTERESTS, []])).toEqual(expected)
    expect(classify([NEEDS, ['dietary']])).toEqual(expected)
  })

  it('unknown questions and options are ignored', () => {
    expect(classify(['bogus', ['work']], [COMPANIONS, ['aliens']])).toEqual(result(DEFAULT_TYPE, []))
  })

  it('single choice questions only count the first valid answer', () => {
    expect(classify([COMPANIONS, ['nope', 'work', 'family_kids']]).primary).toBe('BUSINESS')
  })

  it('duplicate answers count once', () => {
    expect(nonZero(scores({ [INTERESTS]: ['food', 'food'] }))).toEqual({ CULTURE_FOODIE: 2 })
  })

  it('classification is deterministic', () => {
    const answers = { [COMPANIONS]: ['friends'], [INTERESTS]: ['adventure', 'nightlife', 'food'], [PACE]: ['packed'] }
    const first = classifyMap(answers)
    for (let i = 0; i < 5; i++) expect(classifyMap(answers)).toEqual(first)
  })

  it('every option weight targets a scored type', () => {
    for (const option of QUESTIONS.flatMap((q) => q.options)) {
      expect(Object.keys(option.weights || {})).not.toContain('ACCESSIBLE')
      for (const w of Object.values(option.weights || {})) expect(w).toBeGreaterThan(0)
      for (const t of Object.keys(option.weights || {})) expect(TRAVELLER_TYPES).toContain(t)
    }
  })

  // Web-only: answers come back from localStorage, so junk must not throw.
  it('tolerates malformed stored answers', () => {
    expect(classifyMap(null)).toEqual(result(DEFAULT_TYPE, []))
    expect(classifyMap({ [COMPANIONS]: 'work', [INTERESTS]: [null, 3, 'food'] })).toEqual(result('CULTURE_FOODIE', []))
  })
})
