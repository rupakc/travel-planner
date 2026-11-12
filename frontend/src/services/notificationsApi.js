import axios from 'axios'
import { watchAxios } from './sessionRevoked'
import { unwrap } from './apiError'

// Notifications 2.0 settings (/api/notification-settings, docs/Notifications-API.md).
// Callers feature-detect `features.notifications_api` in /api/config first.
const http = watchAxios(axios.create({ baseURL: '/api' }))
const auth = (token) => ({ headers: { Authorization: `Bearer ${token}` } })

export const getNotificationSettings = (token) => unwrap(http.get('/notification-settings', auth(token)))
// `patch`: any subset of {categories: {name: {enabled}}, quiet_hours, daily_cap}.
export const putNotificationSettings = (token, patch) =>
  unwrap(http.put('/notification-settings', patch, auth(token)))
