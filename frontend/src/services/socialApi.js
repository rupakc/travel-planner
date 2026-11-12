import axios from 'axios'
import { watchAxios } from './sessionRevoked'
import { unwrap } from './apiError'

// Phase 5 social API (docs/Social-API.md). Every call needs a signed-in token.
const http = watchAxios(axios.create({ baseURL: '/api', headers: { 'Content-Type': 'application/json' } }))
const bearer = (token) => ({ headers: { Authorization: `Bearer ${token}` } })
const seg = (v) => encodeURIComponent(String(v))
const page = (cursor, extra = {}) => ({ params: { ...extra, ...(cursor ? { cursor } : {}) } })

export const getOwnProfile = (token) => unwrap(http.get('/social/profile', bearer(token)))
export const putProfile = (token, body) => unwrap(http.put('/social/profile', body, bearer(token)))
export const getProfile = (token, handle) => unwrap(http.get(`/social/profile/${seg(handle)}`, bearer(token)))
export const checkHandle = (token, handle) =>
  unwrap(http.get('/social/handles/check', { ...bearer(token), params: { handle } }))

export const follow = (token, handle) => unwrap(http.put(`/social/follow/${seg(handle)}`, null, bearer(token)))
export const unfollow = (token, handle) => unwrap(http.delete(`/social/follow/${seg(handle)}`, bearer(token)))
export const listFollowRequests = (token) => unwrap(http.get('/social/follow-requests', bearer(token)))
export const acceptRequest = (token, handle) =>
  unwrap(http.post(`/social/follow-requests/${seg(handle)}/accept`, null, bearer(token)))
export const declineRequest = (token, handle) =>
  unwrap(http.post(`/social/follow-requests/${seg(handle)}/decline`, null, bearer(token)))
export const blockUser = (token, handle) => unwrap(http.put(`/social/block/${seg(handle)}`, null, bearer(token)))
export const unblockUser = (token, handle) => unwrap(http.delete(`/social/block/${seg(handle)}`, bearer(token)))
export const listBlocks = (token) => unwrap(http.get('/social/blocks', bearer(token)))

export const getFeed = (token, { scope = 'for_you', cursor = null, limit = 20 } = {}) =>
  unwrap(http.get('/social/feed', { ...bearer(token), ...page(cursor, { scope, limit }) }))
export const getIdea = (token, id) => unwrap(http.get(`/social/ideas/${seg(id)}`, bearer(token)))
export const getProfileIdeas = (token, handle, cursor = null) =>
  unwrap(http.get(`/social/profile/${seg(handle)}/ideas`, { ...bearer(token), ...page(cursor) }))
export const publishIdea = (token, body) => unwrap(http.post('/social/ideas', body, bearer(token)))
export const deleteIdea = (token, id) => unwrap(http.delete(`/social/ideas/${seg(id)}`, bearer(token)))
export const likeIdea = (token, id) => unwrap(http.put(`/social/ideas/${seg(id)}/like`, null, bearer(token)))
export const unlikeIdea = (token, id) => unwrap(http.delete(`/social/ideas/${seg(id)}/like`, bearer(token)))
export const saveIdea = (token, id) => unwrap(http.post(`/social/ideas/${seg(id)}/save`, null, bearer(token)))

export const listComments = (token, id, cursor = null) =>
  unwrap(http.get(`/social/ideas/${seg(id)}/comments`, { ...bearer(token), ...page(cursor) }))
export const addComment = (token, id, text) =>
  unwrap(http.post(`/social/ideas/${seg(id)}/comments`, { text }, bearer(token)))
export const deleteComment = (token, id) => unwrap(http.delete(`/social/comments/${seg(id)}`, bearer(token)))
export const markHelpful = (token, id) => unwrap(http.put(`/social/comments/${seg(id)}/helpful`, null, bearer(token)))
export const unmarkHelpful = (token, id) => unwrap(http.delete(`/social/comments/${seg(id)}/helpful`, bearer(token)))

export const sendReport = (token, body) => unwrap(http.post('/social/reports', body, bearer(token)))
