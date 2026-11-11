import axios from 'axios'
import { localeField } from './api'
import { unwrap, toApiError } from './apiError'

const http = axios.create({ baseURL: '/api', headers: { 'Content-Type': 'application/json' } })
const bearer = (token) => ({ headers: { Authorization: `Bearer ${token}` } })

export const getAccount = (token) => unwrap(http.get('/account', bearer(token)))
export const updateProfile = (token, body) => unwrap(http.patch('/account', body, bearer(token)))
export const uploadAvatar = (token, file) => {
  const form = new FormData()
  form.append('file', file)
  // Content-Type is left to the browser so the multipart boundary is set.
  return unwrap(http.put('/account/avatar', form, {
    headers: { Authorization: `Bearer ${token}`, 'Content-Type': undefined },
  }))
}
export const removeAvatar = (token) => unwrap(http.delete('/account/avatar', bearer(token)))
export const getSettings = (token) => unwrap(http.get('/account/settings', bearer(token)))
export const patchSettings = (token, patch) =>
  unwrap(http.patch('/account/settings', patch, bearer(token)))
export const putOnboarding = (token, body) =>
  unwrap(http.put('/account/onboarding', body, bearer(token)))
export const unlinkIdentity = (token, provider) =>
  unwrap(http.delete(`/account/identities/${encodeURIComponent(provider)}`, bearer(token)))
export const requestEmailVerification = (token) =>
  unwrap(http.post('/account/email/verify', { ...localeField() }, bearer(token)))
export async function exportAccount(token) {
  try {
    return (await http.get('/account/export', { ...bearer(token), responseType: 'blob' })).data
  } catch (err) {
    throw toApiError(err)
  }
}
export const deleteAccount = (token, body) =>
  unwrap(http.delete('/account', { ...bearer(token), data: body }))
export const getQuota = (token) => unwrap(http.get('/account/quota', bearer(token)))
