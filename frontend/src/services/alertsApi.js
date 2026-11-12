import axios from 'axios'
import { watchAxios } from './sessionRevoked'
import { unwrap } from './apiError'

// Price alerts 2.0 (/api/alerts/*, docs/Alerts-API.md). Every call needs the
// bearer token and resolves to the response body. Callers feature-detect
// `features.alerts_api` (hooks/useAlertsV2) before using any of these.
const http = watchAxios(axios.create({ baseURL: '/api' }))
const auth = (token) => ({ headers: { Authorization: `Bearer ${token}` } })
const watchPath = (kind, id) => `/alerts/watches/${encodeURIComponent(kind)}/${encodeURIComponent(id)}`

export const getSavings = (token) => unwrap(http.get('/alerts/summary', auth(token)))
export const getStory = (token, kind, id) => unwrap(http.get(`${watchPath(kind, id)}/story`, auth(token)))
export const requestAdvice = (token, kind, id) => unwrap(http.post(`${watchPath(kind, id)}/advice`, null, auth(token)))
export const quickWatch = (token, body) => unwrap(http.post('/alerts/quick-watch', body, auth(token)))
export const getSuggestions = (token, planId) =>
  unwrap(http.get('/alerts/suggestions', { ...auth(token), params: { plan_id: planId } }))
export const getAlertPrefs = (token) => unwrap(http.get('/alerts/preferences', auth(token)))
export const putAlertPrefs = (token, patch) => unwrap(http.put('/alerts/preferences', patch, auth(token)))
