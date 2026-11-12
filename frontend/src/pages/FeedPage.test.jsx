// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { MemoryRouter } from 'react-router-dom'

vi.mock('../context/AuthContext', () => ({ useAuth: () => ({ token: 'tok' }) }))
vi.mock('../telemetry/client', () => ({ emit: vi.fn() }))
vi.mock('../services/socialApi', () => ({
  getFeed: vi.fn(), getIdea: vi.fn(), getOwnProfile: vi.fn(),
  likeIdea: vi.fn(), unlikeIdea: vi.fn(), saveIdea: vi.fn(), deleteIdea: vi.fn(), listComments: vi.fn(),
}))

import { initI18n } from '../i18n/index'
import { emit } from '../telemetry/client'
import * as api from '../services/socialApi'
import FeedPage from './FeedPage'

globalThis.IS_REACT_ACT_ENVIRONMENT = true
const mk = (id, title) => ({
  id, kind: 'plan', title, caption: `cap ${id}`, author: { handle: 'ann' }, snapshot: { destinations: ['Lisbon'], days: 3, stats: [], items: {} },
  likes: 0, saves: 0, comments: 0, liked: false, saved: false, mine: false, status: 'published',
})
let container, root
const tid = (id) => container.querySelector(`[data-tid="${id}"]`)
const all = (id) => [...container.querySelectorAll(`[data-tid="${id}"]`)]
const click = async (el) => { await act(async () => { el.dispatchEvent(new MouseEvent('click', { bubbles: true })) }) }
const mount = async (props = {}) => {
  await act(async () => { root.render(<MemoryRouter><FeedPage {...props} /></MemoryRouter>) })
}

beforeEach(async () => {
  await initI18n({ lng: 'en', bundleAll: true })
  vi.clearAllMocks()
  api.getOwnProfile.mockResolvedValue({ handle: 'me_1', visibility: 'public' })
  api.getFeed.mockResolvedValue({ ideas: [mk(1, 'First'), mk(2, 'Second')], next: 'c2' })
  container = document.createElement('div'); document.body.appendChild(container); root = createRoot(container)
})
afterEach(() => { act(() => root.unmount()); container.remove() })

describe('FeedPage', () => {
  it('loads the For you feed, reports the scope and pages with the cursor', async () => {
    await mount()
    expect(api.getFeed).toHaveBeenCalledWith('tok', { scope: 'for_you', cursor: null })
    expect(all('social.idea')).toHaveLength(2)
    expect(emit).toHaveBeenCalledWith('social_feed_view', { scope: 'for_you' })
    api.getFeed.mockResolvedValue({ ideas: [mk(3, 'Third')], next: null })
    await click(tid('social.feed.more'))
    expect(api.getFeed).toHaveBeenLastCalledWith('tok', { scope: 'for_you', cursor: 'c2' })
    expect(all('social.idea')).toHaveLength(3)
    expect(tid('social.feed.more')).toBeNull()
  })

  it('switches scope and reloads from the top', async () => {
    await mount()
    api.getFeed.mockResolvedValue({ ideas: [], next: null })
    await click(tid('social.feed.scope.following'))
    expect(api.getFeed).toHaveBeenLastCalledWith('tok', { scope: 'following', cursor: null })
    expect(tid('social.feed.empty').textContent).toMatch(/follow/)
    expect(emit).toHaveBeenCalledWith('social_feed_view', { scope: 'following' })
    expect(tid('social.feed.scope.following').getAttribute('aria-selected')).toBe('true')
  })

  it('shows an error with retry', async () => {
    api.getFeed.mockRejectedValueOnce({ status: 500, code: null, detail: 'boom' })
    await mount()
    expect(tid('social.feed.error').textContent).toContain('boom')
    await click(tid('social.feed.retry'))
    expect(all('social.idea')).toHaveLength(2)
  })

  it('prompts for a profile when there is none', async () => {
    api.getOwnProfile.mockResolvedValue({ handle: null, visibility: 'private' })
    await mount()
    expect(tid('social.feed.profilePrompt')).not.toBeNull()
    expect(tid('social.feed.createProfile').getAttribute('href')).toBe('/u/me')
    expect(tid('social.feed.myProfile')).toBeNull()
  })

  it('renders hostile idea text as plain text', async () => {
    api.getFeed.mockResolvedValue({ ideas: [mk(1, '<img src=x onerror=alert(1)>')], next: null })
    await mount()
    expect(tid('social.idea.title').textContent).toBe('<img src=x onerror=alert(1)>')
    expect(container.querySelector('img')).toBeNull()
  })

  it('opens one idea with its comments and tells when it is gone', async () => {
    api.getIdea.mockResolvedValue(mk(5, 'Solo'))
    api.listComments.mockResolvedValue({ comments: [], next: null })
    await mount({ ideaId: 5 })
    expect(api.getIdea).toHaveBeenCalledWith('tok', 5)
    expect(tid('social.idea.title').textContent).toBe('Solo')
    expect(tid('social.comments')).not.toBeNull()
    expect(emit).toHaveBeenCalledWith('social_idea_open', undefined)
    api.getIdea.mockRejectedValue({ status: 404, code: 'idea_not_found', detail: '' })
    await mount({ ideaId: 6 })
    expect(tid('social.idea.unavailable').textContent).toBe('This idea is not available.')
  })
})
