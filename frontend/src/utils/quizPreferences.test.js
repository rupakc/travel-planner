// Ported case by case from Android
// core/domain/src/test/.../profile/PreferencesMappingTest.kt
// (rupakc/travel-planner-android): the quiz must write the same server
// Preferences from every client.
import { describe, it, expect, beforeEach } from 'vitest'
import { QUESTIONS } from './travellerQuiz'
import {
  mergeQuizAnswers, quizPace, loadQuizAnswers, saveQuizAnswers,
} from './quizPreferences'

const COMPANIONS = 'companions'
const BUDGET = 'budget'
const INTERESTS = 'interests'
const NEEDS = 'needs'
const PACE = 'pace'

// Android's `Preferences()` defaults (the server's DEFAULT_PREFS).
const Preferences = (over = {}) => ({
  budget_category: 'medium',
  nationality: '',
  current_residence: '',
  residence_permits: [],
  existing_visas: [],
  interests: [],
  num_travelers: 1,
  adults: 1,
  children: 0,
  seniors: 0,
  infants: 0,
  accessibility_needs: [],
  ...over,
})

describe('mergeQuizAnswers (Android PreferencesMappingTest)', () => {
  // The web's 10 interest ids and 4 accessibility ids (SearchPage INTERESTS, TravelerPanel).
  const webInterests = ['food', 'history', 'adventure', 'culture', 'nature', 'shopping', 'nightlife', 'wellness', 'art', 'family']
  const webAccessibility = ['wheelchair', 'visual_impairment', 'hearing_impairment', 'cognitive_disability']

  it('only web interest and accessibility ids are produced, and all are reachable', () => {
    const options = QUESTIONS.flatMap((q) => q.options)
    const interests = new Set(options.flatMap((o) => o.interestIds || []))
    const needs = new Set(options.map((o) => o.accessibilityId).filter(Boolean))
    expect([...interests].sort()).toEqual([...webInterests].sort())
    expect([...needs].sort()).toEqual([...webAccessibility].sort())
    for (const c of options.map((o) => o.budgetCategory).filter(Boolean)) expect(['low', 'medium', 'high']).toContain(c)
  })

  it('budget maps shoestring low, mid and comfort medium, luxury high', () => {
    const cases = { shoestring: 'low', mid_range: 'medium', comfort: 'medium', luxury: 'high' }
    for (const [answer, category] of Object.entries(cases)) {
      expect(mergeQuizAnswers(Preferences(), { [BUDGET]: [answer] }).budget_category).toBe(category)
    }
  })

  it('skipped answers keep every existing field', () => {
    const existing = Preferences({
      username: 'alice',
      budget_category: 'high',
      nationality: 'Indian',
      current_residence: 'Munich, Germany',
      residence_permits: ['Schengen'],
      existing_visas: ['US'],
      interests: ['art'],
      num_travelers: 4,
      adults: 2,
      children: 1,
      seniors: 1,
      accessibility_needs: ['hearing_impairment'],
    })
    expect(mergeQuizAnswers(existing, {})).toEqual(existing)
  })

  it('lists are merged, never wiped', () => {
    const existing = Preferences({ interests: ['art', 'food'], accessibility_needs: ['hearing_impairment'] })
    const merged = mergeQuizAnswers(existing, {
      [INTERESTS]: ['food', 'history_culture', 'beaches'],
      [NEEDS]: ['wheelchair', 'dietary'],
    })
    expect(merged.interests).toEqual(['art', 'food', 'history', 'culture', 'nature', 'wellness'])
    expect(merged.accessibility_needs).toEqual(['hearing_impairment', 'wheelchair'])
  })

  it('companions fill the default party and recount', () => {
    const family = mergeQuizAnswers(Preferences(), { [COMPANIONS]: ['family_kids'] })
    expect(family.adults).toBe(2)
    expect(family.children).toBe(1)
    expect(family.num_travelers).toBe(3)
    expect(family.interests).toContain('family')

    const partner = mergeQuizAnswers(Preferences(), { [COMPANIONS]: ['partner'] })
    expect(partner.adults).toBe(2)
    expect(partner.num_travelers).toBe(2)
  })

  it('a party the user already set is never overwritten', () => {
    const bigFamily = Preferences({ adults: 2, children: 3, num_travelers: 5 })
    expect(mergeQuizAnswers(bigFamily, { [COMPANIONS]: ['family_kids'] })).toEqual({ ...bigFamily, interests: ['family'] })

    const soloWithSenior = Preferences({ adults: 1, seniors: 1, num_travelers: 2 })
    expect(mergeQuizAnswers(soloWithSenior, { [COMPANIONS]: ['solo'] })).toEqual(soloWithSenior)
    expect(mergeQuizAnswers(soloWithSenior, { [COMPANIONS]: ['work'] })).toEqual(soloWithSenior)
  })

  it('infants stay a minimum on a custom party', () => {
    const merged = mergeQuizAnswers(Preferences({ adults: 2, children: 3, num_travelers: 5 }), {
      [COMPANIONS]: ['family_kids'],
      [NEEDS]: ['infants'],
    })
    expect(merged.adults).toBe(2)
    expect(merged.children).toBe(3)
    expect(merged.infants).toBe(1)
    expect(merged.num_travelers).toBe(6)
  })

  it('infants need adds one infant unless there already are some', () => {
    expect(mergeQuizAnswers(Preferences(), { [NEEDS]: ['infants'] }).infants).toBe(1)
    expect(mergeQuizAnswers(Preferences(), { [NEEDS]: ['infants'] }).num_travelers).toBe(2)
    expect(mergeQuizAnswers(Preferences({ infants: 2, num_travelers: 3 }), { [NEEDS]: ['infants'] }).infants).toBe(2)
  })

  it('traveller total is clamped to the server range', () => {
    const merged = mergeQuizAnswers(Preferences({ adults: 20, children: 20, num_travelers: 20 }), { [NEEDS]: ['infants'] })
    expect(merged.num_travelers).toBe(20)
  })

  it('pace is read for the search form', () => {
    expect(quizPace({ [PACE]: ['packed'] })).toBe('packed')
    expect(quizPace({})).toBeNull()
  })

  // Web-only: the GET may lack newer columns (an old row) — defaults fill them.
  it('fills missing fields with the server defaults', () => {
    const merged = mergeQuizAnswers({ nationality: 'Indian' }, { [COMPANIONS]: ['partner'] })
    expect(merged).toEqual(Preferences({ nationality: 'Indian', adults: 2, num_travelers: 2 }))
  })

  it('does not mutate its input', () => {
    const existing = Preferences({ interests: ['art'] })
    mergeQuizAnswers(existing, { [INTERESTS]: ['food'], [COMPANIONS]: ['work'] })
    expect(existing).toEqual(Preferences({ interests: ['art'] }))
  })
})

describe('quiz answer storage', () => {
  beforeEach(() => { try { localStorage.clear() } catch { /* none */ } })

  it('keeps answers per user in tp_quiz_<user_id>', () => {
    saveQuizAnswers('u1', { pace: ['packed'] })
    expect(JSON.parse(localStorage.getItem('tp_quiz_u1'))).toEqual({ pace: ['packed'] })
    expect(loadQuizAnswers('u1')).toEqual({ pace: ['packed'] })
    expect(loadQuizAnswers('u2')).toEqual({})
  })

  it('reads junk as no answers', () => {
    localStorage.setItem('tp_quiz_u1', '{oops')
    expect(loadQuizAnswers('u1')).toEqual({})
    localStorage.setItem('tp_quiz_u1', '[1]')
    expect(loadQuizAnswers('u1')).toEqual({})
    expect(loadQuizAnswers(null)).toEqual({})
  })
})
