// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { act } from 'react'
import { createRoot } from 'react-dom/client'

const getAuthProviders = vi.fn()
vi.mock('../../services/api', () => ({ getAuthProviders: (...a) => getAuthProviders(...a) }))
const navigateTo = vi.fn()
vi.mock('./navigate', () => ({ navigateTo: (...a) => navigateTo(...a) }))

import SocialSignInButtons from './SocialSignInButtons'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

let container, root
const render = async (props = {}) => act(async () => root.render(<SocialSignInButtons {...props} />))
const click = async (el) => act(async () => { el.dispatchEvent(new MouseEvent('click', { bubbles: true })) })
const btn = (id) => container.querySelector(`[data-tid="auth.provider.${id}"]`)

beforeEach(() => {
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
  getAuthProviders.mockReset(); navigateTo.mockReset()
})
afterEach(() => { act(() => root.unmount()); container.remove() })

describe('SocialSignInButtons', () => {
  it('renders Apple, Google, Facebook, GitHub in order', async () => {
    getAuthProviders.mockResolvedValue([])
    await render()
    const buttons = [...container.querySelectorAll('button')]
    expect(buttons.map((b) => b.dataset.tid)).toEqual([
      'auth.provider.apple', 'auth.provider.google', 'auth.provider.facebook', 'auth.provider.github',
    ])
    expect(buttons[1].textContent).toBe('Continue with Google')
    expect(buttons[0].querySelector('svg[aria-hidden="true"]')).not.toBeNull()
  })

  it('shows the coming-soon note, without navigating, when providers are unavailable', async () => {
    getAuthProviders.mockResolvedValue([])
    await render()
    await click(btn('google'))
    const note = container.querySelector('[aria-live="polite"]')
    expect(note.textContent).toBe('Google sign-in is coming soon — use your username and password for now.')
    expect(navigateTo).not.toHaveBeenCalled()
  })

  it('navigates to start_url when configured', async () => {
    getAuthProviders.mockResolvedValue([{ id: 'github', configured: true, start_url: '/api/auth/github/start' }])
    await render()
    await click(btn('github'))
    expect(navigateTo).toHaveBeenCalledWith('/api/auth/github/start')
  })

  it('treats an off-site start_url as not configured', async () => {
    getAuthProviders.mockResolvedValue([{ id: 'github', configured: true, start_url: 'https://evil.example/x' }])
    await render()
    await click(btn('github'))
    expect(navigateTo).not.toHaveBeenCalled()
    expect(container.querySelector('[aria-live="polite"]').textContent).toMatch(/GitHub sign-in is coming soon/)
  })

  it.each([
    '/api/auth/../x',
    '/api/auth/%2e%2e/x',
    '/api/auth/%2E%2E/x',
    '//evil.com/api/auth/',
    '/api/auth\\x',
  ])('treats %s as not configured', async (start) => {
    getAuthProviders.mockResolvedValue([{ id: 'github', configured: true, start_url: start }])
    await render()
    await click(btn('github'))
    expect(navigateTo).not.toHaveBeenCalled()
    expect(container.querySelector('[aria-live="polite"]').textContent).toMatch(/coming soon/)
  })

  it('keeps the query string of a valid start_url', async () => {
    getAuthProviders.mockResolvedValue([{ id: 'google', configured: true, start_url: '/api/auth/google/start?x=1' }])
    await render()
    await click(btn('google'))
    expect(navigateTo).toHaveBeenCalledWith('/api/auth/google/start?x=1')
  })

  it('fetches providers once and renders the same buttons in signup mode', async () => {
    getAuthProviders.mockResolvedValue([])
    await render({ mode: 'signup' })
    expect(getAuthProviders).toHaveBeenCalledTimes(1)
    expect(container.querySelectorAll('button').length).toBe(4)
  })
})

describe('SocialSignInButtons theming', () => {
  // Palette names (white, gray-*, neutral-*, …) are CSS variables that html.dark
  // swaps (white becomes navy), so a brand colour must be a literal hex or black.
  it('uses literal brand colours that dark mode cannot remap', async () => {
    getAuthProviders.mockResolvedValue([])
    await render()
    for (const b of container.querySelectorAll('[data-tid^="auth.provider."]')) {
      const themed = b.className.split(/\s+/).filter((c) =>
        /^(?:dark:)?(?:hover:)?(?:bg|text|border)-(?!\[#|black$)[a-z]+(?:-\d+)?$/.test(c)
        && !/-(?:sm|xs|lg)$/.test(c))
      expect(themed, b.dataset.tid).toEqual([])
    }
  })

  it('Apple is a white button with a visible edge in dark mode', async () => {
    getAuthProviders.mockResolvedValue([])
    await render()
    const cls = btn('apple').className.split(/\s+/)
    expect(cls).toEqual(expect.arrayContaining(['dark:bg-[#ffffff]', 'dark:text-[#000000]']))
    expect(cls.some((c) => c.startsWith('dark:border-[#'))).toBe(true)
  })

  it('the coming-soon note is body-sized, normal contrast, with an info icon', async () => {
    getAuthProviders.mockResolvedValue([])
    await render()
    await click(btn('apple'))
    const note = container.querySelector('[data-tid="auth.coming-soon"]')
    expect(note.className).toContain('text-sm')
    expect(note.className).not.toMatch(/text-slate-[45]00|text-gray-[45]00/)
    expect(note.querySelector('svg[aria-hidden="true"]')).not.toBeNull()
  })
})
