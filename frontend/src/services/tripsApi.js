// Trips API (docs/Trips-API.md). Every function takes the bearer token first,
// resolves with the response body and rejects with toApiError(...); a request
// that never got an answer (offline, DNS, CORS) rejects with code 'network'.
// GETs, the check-in and recap completion send the device's local date as
// `today`, so the server sees the traveller's day, not UTC's.
import axios from 'axios'
import { watchAxios } from './sessionRevoked'
import { toApiError } from './apiError'
import { localToday } from '../utils/tripPhase'

const http = watchAxios(axios.create({ baseURL: '/api', headers: { 'Content-Type': 'application/json' } }))
const bearer = (token) => ({ headers: { Authorization: `Bearer ${token}` } })
const dated = (token) => ({ ...bearer(token), params: { today: localToday() } })

async function call(promise) {
  try {
    return (await promise).data
  } catch (err) {
    const apiErr = toApiError(err)
    if (!err?.response) apiErr.code = 'network'
    throw apiErr
  }
}

const trip = (id) => `/trips/${encodeURIComponent(id)}`
const child = (id, ...parts) => [trip(id), ...parts.map((p) => encodeURIComponent(p))].join('/')

// Trips
export const listTrips = (token) => call(http.get('/trips', dated(token)))
export const getTripStats = (token) => call(http.get('/trips/stats', dated(token)))
export const getTrip = (token, id) => call(http.get(trip(id), dated(token)))
export const createTrip = (token, body) => call(http.post('/trips', body, bearer(token)))
export const patchTrip = (token, id, changes) => call(http.patch(trip(id), changes, bearer(token)))
export const deleteTrip = (token, id) => call(http.delete(trip(id), bearer(token)))

// Prep, snapshot, offline pack
export const getPrep = (token, id) => call(http.get(child(id, 'prep'), dated(token)))
export const setPrepItem = (token, id, itemId, done) =>
  call(http.put(child(id, 'prep', itemId), { done: !!done }, bearer(token)))
export const putSnapshot = (token, id, snapshot) =>
  call(http.put(child(id, 'snapshot'), snapshot, bearer(token)))
export const getOfflinePack = (token, id) => call(http.get(child(id, 'offline-pack'), dated(token)))

// Expenses
export const listExpenses = (token, id) => call(http.get(child(id, 'expenses'), dated(token)))
export const addExpense = (token, id, body) => call(http.post(child(id, 'expenses'), body, bearer(token)))
export const updateExpense = (token, id, eid, changes) =>
  call(http.patch(child(id, 'expenses', eid), changes, bearer(token)))
export const deleteExpense = (token, id, eid) => call(http.delete(child(id, 'expenses', eid), bearer(token)))

// Journal
export const listJournal = (token, id) => call(http.get(child(id, 'journal'), dated(token)))
export const addJournal = (token, id, body) => call(http.post(child(id, 'journal'), body, bearer(token)))
export const updateJournal = (token, id, eid, changes) =>
  call(http.patch(child(id, 'journal', eid), changes, bearer(token)))
export const deleteJournal = (token, id, eid) => call(http.delete(child(id, 'journal', eid), bearer(token)))

// Places (ratings, visits); keys come from utils/placeKey.js
export const listPlaces = (token, id) => call(http.get(child(id, 'places'), dated(token)))
export const putPlace = (token, id, key, body) => call(http.put(child(id, 'places', key), body, bearer(token)))
export const deletePlace = (token, id, key) => call(http.delete(child(id, 'places', key), bearer(token)))

// Today and recap
export const checkIn = (token, id, day) => call(http.post(child(id, 'checkin'), { day }, dated(token)))
export const listCheckins = (token, id) => call(http.get(child(id, 'checkins'), dated(token)))
export const getRecap = (token, id) => call(http.get(child(id, 'recap'), dated(token)))
export const completeRecap = (token, id) => call(http.post(child(id, 'recap', 'complete'), null, dated(token)))
