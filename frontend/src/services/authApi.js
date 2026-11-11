import axios from 'axios'
import { watchAxios } from './sessionRevoked'
import { localeField } from './api'
import { unwrap } from './apiError'

const http = watchAxios(axios.create({ baseURL: '/api', headers: { 'Content-Type': 'application/json' } }))
const bearer = (token) => ({ headers: { Authorization: `Bearer ${token}` } })
const base = () => ({ client: 'web', ...localeField() })

export const signup = (body) => unwrap(http.post('/auth/signup', { ...body, ...base() }))
export const resendVerification = (email) =>
  unwrap(http.post('/auth/verify-email/resend', { email, ...base() }))
export const verifyEmail = (token) => unwrap(http.post('/auth/verify-email', { token, ...base() }))
export const requestPasswordReset = (email) =>
  unwrap(http.post('/auth/password-reset/request', { email, ...base() }))
export const confirmPasswordReset = (token, newPassword) =>
  unwrap(http.post('/auth/password-reset/confirm', { token, new_password: newPassword, ...base() }))
// The tp_oauth binding cookie is same-origin: sent with the request.
export const exchangeOAuthCode = (code) =>
  unwrap(http.post('/auth/oauth/exchange', { code, ...base() }, { withCredentials: true }))
export const completeOAuthSignup = (body) =>
  unwrap(http.post('/auth/oauth/complete', { ...body, ...base() }))
export const getLinkStartUrl = (token, provider) =>
  unwrap(http.post('/auth/oauth/link-ticket', { provider, ...base() }, bearer(token)))
export const logoutAll = (token) => unwrap(http.post('/auth/logout-all', {}, bearer(token)))
export const changePasswordV2 = (token, current, next) =>
  unwrap(http.post('/auth/change-password',
    { current_password: current, new_password: next, ...base() }, bearer(token)))
