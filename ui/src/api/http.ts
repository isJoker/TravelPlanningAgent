import axios from 'axios'

/** Base URL: empty by default (uses Vite dev proxy). */
const baseURL = import.meta.env.VITE_API_BASE || ''

export const http = axios.create({
  baseURL,
  timeout: 30000,
  headers: { 'Content-Type': 'application/json' },
})

http.interceptors.response.use(
  (r) => r,
  (err) => {
    console.error('[http] error', err?.response?.status, err?.response?.data || err.message)
    return Promise.reject(err)
  }
)
