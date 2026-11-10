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

  it('fetches providers once and renders the same buttons in signup mode', async () => {
    getAuthProviders.mockResolvedValue([])
    await render({ mode: 'signup' })
    expect(getAuthProviders).toHaveBeenCalledTimes(1)
    expect(container.querySelectorAll('button').length).toBe(4)
  })
})
