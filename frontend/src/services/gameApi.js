import axios from 'axios'
import { unwrap } from './apiError'

const http = axios.create({ baseURL: '/api' })

export const getGameMe = (token) =>
  unwrap(http.get('/game/me', { headers: { Authorization: `Bearer ${token}` } }))
export const getGameCatalog = () => unwrap(http.get('/game/catalog'))
