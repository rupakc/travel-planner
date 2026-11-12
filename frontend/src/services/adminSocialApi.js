import axios from 'axios'
import { watchAxios } from './sessionRevoked'
import { unwrap } from './apiError'

const http = watchAxios(axios.create({ baseURL: '/api', headers: { 'Content-Type': 'application/json' } }))
const bearer = (token) => ({ headers: { Authorization: `Bearer ${token}` } })
const enc = encodeURIComponent

// A 404 here means no backend support (or SOCIAL_ENABLED off): the Moderation tab stays hidden.
export const listQueue = (token, status = 'held', cursor) =>
  unwrap(http.get('/admin/social/queue', { ...bearer(token), params: { status, ...(cursor ? { cursor } : {}) } }))
export const decide = (token, target, id, action) =>
  unwrap(http.post(`/admin/social/${enc(target)}/${enc(id)}/decide`, { action }, bearer(token)))
export const restrictUser = (token, handle, days) =>
  unwrap(http.post(`/admin/social/users/${enc(handle)}/restrict`, { days }, bearer(token)))
export const liftRestriction = (token, handle) =>
  unwrap(http.delete(`/admin/social/users/${enc(handle)}/restrict`, bearer(token)))
