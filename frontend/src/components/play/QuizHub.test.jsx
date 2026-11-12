// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { MemoryRouter, Routes, Route } from 'react-router-dom'

vi.mock('../../services/playApi', () => ({
  getPlayState: vi.fn(), startQuiz: vi.fn(), answerQuiz: vi.fn(), getH2H: vi.fn(), createH2H: vi.fn(),
  acceptH2H: vi.fn(), declineH2H: vi.fn(), getLeaderboard: vi.fn(), getSocialProfile: vi.fn(), saveSocialProfile: vi.fn(),
}))
vi.mock('../../telemetry/client', () => ({ emit: vi.fn() }))

import { initI18n } from '../../i18n/index'
import * as api from '../../services/playApi'
import { emit } from '../../telemetry/client'
import QuizHub from './QuizHub'
import H2HMatch from './H2HMatch'

globalThis.IS_REACT_ACT_ENVIRONMENT = true
const STATE = {
  daily: { available: true, done: false, score: null, streak: { current: 2, longest: 4, freeze_available: true } },
  packs: [{ id: 'flags', title_key: 'x', questions: 40 }, { id: 'capitals', title_key: 'y', questions: 40 }],
  challenge: { id: '2026-W46:JP', kind: 'destination', country: 'JP', done: false },
  open_h2h: 0,
}
const SESSION = {
  session_id: 's1', mode: 'daily', pack: null, answers: [],
  questions: [
    { index: 0, kind: 'flag', prompt: { template: 'flag', flag: '\u{1F1EF}\u{1F1F5}' },
      options: [{ id: 'a', code: 'JP', label: 'Japan' }, { id: 'b', code: 'FR', label: 'France' }] },
    { index: 1, kind: 'capital_of', prompt: { template: 'capital_of', country: 'France', code: 'FR' },
      options: [{ id: 'a', label: 'Paris' }, { id: 'b', label: 'Lyon' }] },
  ],
}
let container, root
const tid = (id) => container.querySelector(`[data-tid="${id}"]`)
const click = async (id) => { await act(async () => { tid(id).dispatchEvent(new MouseEvent('click', { bubbles: true })) }) }
const mount = async (el) => {
  await act(async () => { root.render(<MemoryRouter initialEntries={['/play']}>{el}</MemoryRouter>) })
}

beforeEach(async () => {
  await initI18n({ lng: 'en' })
  vi.clearAllMocks()
  api.getPlayState.mockResolvedValue(STATE)
  api.getH2H.mockResolvedValue({ matches: [{ id: 'm1', opponent: { handle: 'ana' }, pack: 'flags', state: 'waiting_you', you: null, them: null, winner: null }] })
  api.getLeaderboard.mockResolvedValue({ week: '2026-W46', rows: [{ rank: 1, handle: 'bo', score: 700, you: false }], you: { rank: 4, score: 100, opted_in: false } })
  api.getSocialProfile.mockResolvedValue({ handle: null })
  api.startQuiz.mockResolvedValue(SESSION)
  container = document.createElement('div'); document.body.appendChild(container); root = createRoot(container)
})
afterEach(() => { act(() => root.unmount()); container.remove() })

describe('QuizHub', () => {
  it('renders nothing when Play is unavailable (hidden game or old backend)', async () => {
    api.getPlayState.mockRejectedValue({ status: 403, code: 'game_hidden' })
    await mount(<QuizHub token="t" />)
    expect(tid('play.hub')).toBeNull()
    expect(container.textContent).toBe('')
  })

  it('shows daily, challenge, packs, h2h and the board', async () => {
    await mount(<QuizHub token="t" />)
    expect(tid('play.daily.start')).not.toBeNull()
    expect(tid('play.daily.streak').textContent).toContain('2')
    expect(tid('play.challenge').textContent).toContain('Japan')
    expect(tid('play.pack.flags')).not.toBeNull()
    expect(tid('play.h2h.list').textContent).toContain('ana')
    expect(tid('play.board.rows').textContent).toContain('bo')
    expect(emit).toHaveBeenCalledWith('play_state_view')
    expect(emit).toHaveBeenCalledWith('play_challenge_view')
    expect(emit).toHaveBeenCalledWith('play_board_view', { scope: 'friends' })
  })

  it('plays a quiz, reveals answers and shows the result with XP', async () => {
    api.answerQuiz
      .mockResolvedValueOnce({ correct: true, correct_choice: 'a', points: 140, elapsed_ms: 3000, done: false })
      .mockResolvedValueOnce({ correct: false, correct_choice: 'a', points: 0, elapsed_ms: 9000, done: true,
        summary: { score: 140, correct: 1, total: 2, xp: { xp: 10, awards: [{ rule: 'quiz_daily', points: 10 }] }, streak: { current: 3 } } })
    await mount(<QuizHub token="t" />)
    await click('play.daily.start')
    expect(api.startQuiz).toHaveBeenCalledWith('t', expect.objectContaining({ mode: 'daily' }))
    expect(emit).toHaveBeenCalledWith('play_quiz_start', { mode: 'daily', pack: 'none' })
    expect(tid('play.quiz.prompt').textContent).toMatch(/flag/i)
    await click('play.quiz.option.a')
    expect(api.answerQuiz).toHaveBeenCalledWith('t', 's1', 0, 'a')
    expect(emit).toHaveBeenCalledWith('play_quiz_answer', { correct: true, elapsed_s: 3 })
    expect(tid('play.quiz.reveal').textContent).toContain('140')
    await click('play.quiz.next')
    expect(tid('play.quiz.prompt').textContent).toContain('France')
    await click('play.quiz.option.b')
    await click('play.quiz.next')
    expect(tid('play.result.score').textContent).toBe('140')
    expect(tid('play.result.xp').textContent).toContain('10')
    expect(tid('play.result.share.seam')).not.toBeNull()
    expect(emit).toHaveBeenCalledWith('play_quiz_done', { mode: 'daily', correct: 1 })
  })

  it('resumes at the first unanswered question', async () => {
    api.startQuiz.mockResolvedValue({ ...SESSION, resumed: true, answers: [{ index: 0, choice: 'a', correct: true, correct_choice: 'a', points: 100, elapsed_ms: 1 }] })
    await mount(<QuizHub token="t" />)
    await click('play.daily.start')
    expect(tid('play.quiz.progress').textContent).toContain('2')
  })

  it('creates a head-to-head and starts the creator quiz', async () => {
    api.createH2H.mockResolvedValue({ id: 'm2', session_id: 's2', questions: SESSION.questions })
    await mount(<QuizHub token="t" />)
    await act(async () => {
      const input = tid('play.h2h.handle')
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(input, '@zed')
      input.dispatchEvent(new Event('input', { bubbles: true }))
    })
    await act(async () => { tid('play.h2h.form').dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })) })
    expect(api.createH2H).toHaveBeenCalledWith('t', { handle: 'zed', pack: 'flags' })
    expect(emit).toHaveBeenCalledWith('play_h2h_create')
    expect(tid('play.quiz')).not.toBeNull()
  })

  it('offers the global board opt-in and asks for a handle when there is none', async () => {
    api.saveSocialProfile.mockResolvedValue({})
    await mount(<QuizHub token="t" />)
    await click('play.board.scope.global')
    expect(api.getLeaderboard).toHaveBeenCalledWith('t', 'global', 'current')
    expect(tid('play.board.optin')).not.toBeNull()
    expect(tid('play.board.handle')).not.toBeNull()
    expect(emit).toHaveBeenCalledWith('play_board_view', { scope: 'global' })
  })
})

describe('H2HMatch', () => {
  const route = (id) => (
    <MemoryRouter initialEntries={[`/play/h2h/${id}`]}>
      <Routes><Route path="/play/h2h/:id" element={<H2HMatch token="t" id={id} />} /><Route path="/play" element={<p data-tid="home" />} /></Routes>
    </MemoryRouter>
  )
  it('accepts and plays the same questions', async () => {
    api.acceptH2H.mockResolvedValue({ ...SESSION, session_id: 's3' })
    await act(async () => { root.render(route('m1')) })
    expect(emit).toHaveBeenCalledWith('play_h2h_open')
    await click('play.h2h.accept')
    expect(api.acceptH2H).toHaveBeenCalledWith('t', 'm1')
    expect(tid('play.quiz')).not.toBeNull()
  })

  it('declines and goes back to Play', async () => {
    api.declineH2H.mockResolvedValue(null)
    await act(async () => { root.render(route('m1')) })
    await click('play.h2h.decline')
    expect(tid('home')).not.toBeNull()
  })

  it('shows a finished result and the winner telemetry', async () => {
    api.getH2H.mockResolvedValue({ matches: [{ id: 'm1', opponent: { handle: 'ana' }, state: 'done', you: 400, them: 300, winner: 'you' }] })
    await act(async () => { root.render(route('m1')) })
    expect(tid('play.h2h.result').textContent).toContain('400')
    expect(emit).toHaveBeenCalledWith('play_h2h_result', { winner: 'you' })
  })

  it('says so when the match is unknown', async () => {
    await act(async () => { root.render(route('nope')) })
    expect(tid('play.h2h.missing')).not.toBeNull()
  })
})
