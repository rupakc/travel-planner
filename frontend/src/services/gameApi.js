import axios from 'axios'
import { watchAxios } from './sessionRevoked'
import { unwrap } from './apiError'

const http = watchAxios(axios.create({ baseURL: '/api' }))

export const getGameMe = (token) =>
  unwrap(http.get('/game/me', { headers: { Authorization: `Bearer ${token}` } }))
export const getGameCatalog = () => unwrap(http.get('/game/catalog'))
