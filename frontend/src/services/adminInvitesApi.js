import axios from 'axios'
import { unwrap } from './apiError'

const http = axios.create({ baseURL: '/api', headers: { 'Content-Type': 'application/json' } })
const bearer = (token) => ({ headers: { Authorization: `Bearer ${token}` } })

// A 404 here means the backend has no invites yet: the Invites tab stays hidden.
export const listInvites = (token) => unwrap(http.get('/admin/invites', bearer(token)))
export const createInvite = (token, body) => unwrap(http.post('/admin/invites', body, bearer(token)))
export const revokeInvite = (token, id) =>
  unwrap(http.delete(`/admin/invites/${encodeURIComponent(id)}`, bearer(token)))
