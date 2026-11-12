import axios from 'axios'
import { watchAxios } from './sessionRevoked'
import { unwrap } from './apiError'

// Play (Phase 5): quizzes, head-to-head, leaderboards, weekly challenge.
// Contract: docs/Social-API.md. Every route answers 404 play_disabled when
// the flag is off and 403 game_hidden for users who hide Play and points.
const http = watchAxios(axios.create({ baseURL: '/api', headers: { 'Content-Type': 'application/json' } }))
const bearer = (token) => ({ headers: { Authorization: `Bearer ${token}` } })

export const getPlayState = (token) => unwrap(http.get('/play/state', bearer(token)))
export const startQuiz = (token, body) => unwrap(http.post('/play/quiz', body, bearer(token)))
export const answerQuiz = (token, sessionId, index, choice) =>
  unwrap(http.post(`/play/quiz/${encodeURIComponent(sessionId)}/answer`, { index, choice }, bearer(token)))
export const getH2H = (token) => unwrap(http.get('/play/h2h', bearer(token)))
export const createH2H = (token, body) => unwrap(http.post('/play/h2h', body, bearer(token)))
export const acceptH2H = (token, id) =>
  unwrap(http.post(`/play/h2h/${encodeURIComponent(id)}/accept`, null, bearer(token)))
export const declineH2H = (token, id) =>
  unwrap(http.post(`/play/h2h/${encodeURIComponent(id)}/decline`, null, bearer(token)))
export const getLeaderboard = (token, scope, week) =>
  unwrap(http.get('/play/leaderboard', { ...bearer(token), params: { scope, week } }))
// Opting in lives on the social profile (a handle is required the first time).
export const getSocialProfile = (token) => unwrap(http.get('/social/profile', bearer(token)))
export const saveSocialProfile = (token, body) => unwrap(http.put('/social/profile', body, bearer(token)))
