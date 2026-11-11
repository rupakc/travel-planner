// @vitest-environment jsdom
import { describe, it, expect, vi } from 'vitest'
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join, resolve } from 'node:path'
import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { MemoryRouter } from 'react-router-dom'

vi.mock('./context/AuthContext', () => ({
  useAuth: () => ({ login: vi.fn(), isAuthenticated: false, loading: false, requiresPasswordChange: false }),
}))
vi.mock('./hooks/useClientConfig', async (orig) => ({
  ...(await orig()),
  useClientConfig: () => ({ config: { auth: { signup_available: true, signup_mode: 'open' } }, loaded: true }),
}))
vi.mock('./services/authApi', () => ({ resendVerification: vi.fn() }))

import LoginPage from './pages/LoginPage'
import SignupPage from './pages/SignupPage'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

const root = resolve(__dirname, '..')
const walk = (dir) => readdirSync(dir).flatMap((n) => {
  const p = join(dir, n)
  return statSync(p).isDirectory() ? walk(p) : [p]
})
// iCalendar PRODID stays as is so calendar entries remain stable.
const ALLOWED = new Set([join(root, 'src/utils/planExport.js')])

describe('branding', () => {
  it('has no "Travel Planner" in src or index.html (except the iCalendar PRODID)', () => {
    const files = [join(root, 'index.html'), ...walk(join(root, 'src'))]
      .filter((f) => !f.endsWith('branding.test.js'))
    const hits = files.filter((f) => /Travel Planner/i.test(readFileSync(f, 'utf8')) && !ALLOWED.has(f))
    expect(hits).toEqual([])
    expect(readFileSync(join(root, 'src/utils/planExport.js'), 'utf8')).toContain('PRODID:-//Voyager Travel Planner//')
  })

  it('index.html has the Voyager title and manifest link', () => {
    const html = readFileSync(join(root, 'index.html'), 'utf8')
    expect(html).toContain('<title>Voyager — plan, travel, remember</title>')
    expect(html).toContain('<link rel="manifest" href="/manifest.webmanifest">')
  })

  it('serves a same-origin web manifest', () => {
    const m = JSON.parse(readFileSync(join(root, 'public/manifest.webmanifest'), 'utf8'))
    expect(m.name).toBe('Voyager')
    expect(m.short_name).toBe('Voyager')
    expect(m.start_url).toBe('/')
    expect(m.display).toBe('standalone')
    expect(m.icons).toEqual([{ src: '/favicon.svg', sizes: 'any', type: 'image/svg+xml' }])
  })

  it('chat title says Voyager in every language', () => {
    for (const l of ['en', 'es', 'de', 'fr', 'hi', 'zh', 'bn']) {
      const j = JSON.parse(readFileSync(join(root, `src/i18n/locales/${l}/chat.json`), 'utf8'))
      expect(j.page.title).toMatch(/^Voyager /)
    }
  })

  it.each([['login', LoginPage], ['signup', SignupPage]])('%s heading reads Voyager', async (_n, Page) => {
    const el = document.createElement('div')
    document.body.appendChild(el)
    const r = createRoot(el)
    await act(async () => r.render(createElement(MemoryRouter, null, createElement(Page))))
    expect(el.querySelector('h1').textContent).toBe('Voyager')
    act(() => r.unmount())
  })
})
