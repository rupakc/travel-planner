// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { MemoryRouter } from 'react-router-dom'

vi.mock('../context/AuthContext', () => ({ useAuth: () => ({ token: 'tok' }) }))
vi.mock('../telemetry/client', () => ({ emit: vi.fn() }))
const acct = vi.hoisted(() => ({ settings: { hide_game: false } }))
vi.mock('../components/account/SettingsSync', () => ({ useAccountSettings: () => acct }))
vi.mock('../services/socialApi', () => ({
  getOwnProfile: vi.fn(), getProfile: vi.fn(), getProfileIdeas: vi.fn(), putProfile: vi.fn(), checkHandle: vi.fn(),
  follow: vi.fn(), unfollow: vi.fn(), blockUser: vi.fn(), unblockUser: vi.fn(), sendReport: vi.fn(),
  listFollowRequests: vi.fn(), acceptRequest: vi.fn(), declineRequest: vi.fn(), listBlocks: vi.fn(),
  likeIdea: vi.fn(), unlikeIdea: vi.fn(), saveIdea: vi.fn(), deleteIdea: vi.fn(), listComments: vi.fn(),
}))

import { initI18n } from '../i18n/index'
import { emit } from '../telemetry/client'
import * as api from '../services/socialApi'
import ProfilePage from './ProfilePage'

globalThis.IS_REACT_ACT_ENVIRONMENT = true
const OWN = { handle: 'me_1', visibility: 'public', bio: '', show_avatar: false, show_home_country: false, show_countries: false,
  show_level: false, show_badges: false, leaderboard_opt_in: false, home_country: null }
const PROFILE = { handle: 'ann', bio: '<img src=x onerror=alert(1)>', home_country: 'PT', countries: ['JP', 'PT'], level: 3,
  badges: [{ id: 'first_trip', tier: 1 }], ideas_count: 2, followers_count: 4, following_count: 1,
  you: { following: false, pending: false, follows_you: true, blocked: false } }
let container, root
const tid = (id) => container.querySelector(`[data-tid="${id}"]`)
const click = async (el) => { await act(async () => { el.dispatchEvent(new MouseEvent('click', { bubbles: true })) }) }
const type = async (el, value) => {
  const proto = el.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype
  await act(async () => {
    Object.getOwnPropertyDescriptor(proto, 'value').set.call(el, value)
    el.dispatchEvent(new Event('input', { bubbles: true }))
  })
}
const mount = async (handle) => {
  await act(async () => { root.render(<MemoryRouter><ProfilePage handle={handle} /></MemoryRouter>) })
}

beforeEach(async () => {
  await initI18n({ lng: 'en', bundleAll: true })
  vi.clearAllMocks()
  acct.settings = { hide_game: false }
  api.getOwnProfile.mockResolvedValue(OWN)
  api.getProfile.mockResolvedValue(PROFILE)
  api.getProfileIdeas.mockResolvedValue({ ideas: [], next: null })
  api.listFollowRequests.mockResolvedValue({ requests: [] })
  api.listBlocks.mockResolvedValue({ users: [] })
  api.checkHandle.mockResolvedValue({ available: true })
  container = document.createElement('div'); document.body.appendChild(container); root = createRoot(container)
})
afterEach(() => { act(() => root.unmount()); container.remove() })

describe('ProfilePage (someone else)', () => {
  it('shows only what the server returned, as plain text, and reports a template-only view', async () => {
    await mount('ann')
    expect(api.getProfile).toHaveBeenCalledWith('tok', 'ann')
    expect(tid('social.profile.handle').textContent).toBe('@ann')
    expect(tid('social.profile.bio').textContent).toBe('<img src=x onerror=alert(1)>')
    expect(container.querySelector('img')).toBeNull()
    expect(tid('social.profile.home').textContent).toBe('From Portugal')
    expect(tid('social.profile.countries').textContent).toContain('Japan')
    expect(tid('social.profile.level').textContent).toBe('Level 3')
    expect(tid('social.profile.badge').textContent).toContain('First trip')
    expect(tid('social.profile.counts').textContent).toContain('Followers4')
    expect(emit).toHaveBeenCalledWith('social_profile_view', undefined)
  })

  it('omits sections the owner did not opt into', async () => {
    api.getProfile.mockResolvedValue({ handle: 'bob', ideas_count: 0, followers_count: 0, following_count: 0, you: {} })
    await mount('bob')
    for (const id of ['social.profile.bio', 'social.profile.home', 'social.profile.countries', 'social.profile.level']) expect(tid(id)).toBeNull()
  })

  it('follows (a followers-only profile becomes Requested) and unfollows', async () => {
    api.follow.mockResolvedValue({ state: 'pending' })
    api.unfollow.mockResolvedValue(null)
    await mount('ann')
    await click(tid('social.follow'))
    expect(api.follow).toHaveBeenCalledWith('tok', 'ann')
    expect(tid('social.follow').textContent).toBe('Requested')
    expect(emit).toHaveBeenCalledWith('social_follow', { state: 'pending' })
    await click(tid('social.follow'))
    expect(emit).toHaveBeenCalledWith('social_follow', { state: 'none' })
    expect(tid('social.follow').textContent).toBe('Follow')
  })

  it('updates the Followers count after follow and unfollow', async () => {
    api.getProfile.mockResolvedValue({ ...PROFILE, you: { following: false, pending: false } })
    api.follow.mockResolvedValue({ state: 'following' })
    api.unfollow.mockResolvedValue(null)
    await mount('ann')
    expect(container.textContent).toContain('Followers4')
    await click(tid('social.follow'))
    expect(container.textContent).toContain('Followers5')
    await click(tid('social.follow'))
    expect(container.textContent).toContain('Followers4')
  })

  it('blocks after a confirm and then shows the profile as unavailable', async () => {
    api.blockUser.mockResolvedValue(null)
    await mount('ann')
    await click(tid('social.block'))
    expect(api.blockUser).not.toHaveBeenCalled()
    await click(tid('social.block.yes'))
    expect(api.blockUser).toHaveBeenCalledWith('tok', 'ann')
    expect(emit).toHaveBeenCalledWith('social_block', { on: true })
    expect(tid('social.profile.error').textContent).toBe('This profile is not available.')
  })

  it('reports the profile with an enum reason', async () => {
    api.sendReport.mockResolvedValue(null)
    await mount('ann')
    await click(tid('social.profile.report'))
    await click(tid('social.report.submit'))
    expect(api.sendReport).toHaveBeenCalledWith('tok', { target: 'profile', id: 'ann', reason: 'spam' })
  })

  it('says a private or unknown profile is not available', async () => {
    api.getProfile.mockRejectedValue({ status: 404, code: 'profile_not_found', detail: '' })
    await mount('ghost')
    expect(tid('social.profile.error').textContent).toBe('This profile is not available.')
  })
})

describe('ProfilePage (own profile)', () => {
  it('offers the editor on my own profile and saves changes', async () => {
    api.getProfile.mockResolvedValue({ ...PROFILE, handle: 'me_1' })
    api.putProfile.mockResolvedValue({ ...OWN, visibility: 'followers' })
    await mount('me_1')
    expect(tid('social.follow')).toBeNull()
    await click(tid('social.profile.edit'))
    const sel = tid('social.editor.visibility')
    await act(async () => {
      Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'value').set.call(sel, 'followers')
      sel.dispatchEvent(new Event('change', { bubbles: true }))
    })
    await click(tid('social.editor.show_countries'))
    await click(tid('social.editor.save'))
    expect(api.putProfile).toHaveBeenCalledWith('tok', expect.objectContaining({ visibility: 'followers', show_countries: true, home_country: null }))
    expect(api.putProfile.mock.calls[0][1].handle).toBeUndefined() // handle unchanged: not sent
    expect(emit).toHaveBeenCalledWith('social_profile_save', { visibility: 'followers' })
  })

  it('/u/me creates a profile: needs a handle, checks it, saves it', async () => {
    api.getOwnProfile.mockResolvedValue({ ...OWN, handle: null, visibility: 'private' })
    api.putProfile.mockResolvedValue({ ...OWN, handle: 'newbie', visibility: 'public' })
    await mount('me')
    await type(tid('social.handle.input'), 'Newbie')
    await act(async () => { await new Promise((r) => setTimeout(r, 450)) })
    expect(api.checkHandle).toHaveBeenCalledWith('tok', 'newbie')
    expect(tid('social.handle.hint').textContent).toBe('Available')
    await click(tid('social.editor.save'))
    expect(api.putProfile.mock.calls[0][1]).toEqual(expect.objectContaining({ handle: 'newbie' }))
  })

  it('shows a taken handle and a translated server error', async () => {
    api.getOwnProfile.mockResolvedValue({ ...OWN, handle: null, visibility: 'private' })
    api.checkHandle.mockResolvedValue({ available: false, reason: 'taken' })
    api.putProfile.mockRejectedValue({ status: 409, code: 'handle_taken', detail: '' })
    await mount('me')
    await type(tid('social.handle.input'), 'taken_1')
    await act(async () => { await new Promise((r) => setTimeout(r, 450)) })
    expect(tid('social.handle.hint').textContent).toBe('That handle is taken.')
    await click(tid('social.editor.save'))
    expect(tid('social.editor.error').textContent).toBe('That handle is taken.')
  })

  it('hides the game-only switches for hide_game accounts', async () => {
    acct.settings = { hide_game: true }
    await mount('me')
    expect(tid('social.editor.show_level')).toBeNull()
    expect(tid('social.editor.show_badges')).toBeNull()
    expect(tid('social.editor.leaderboard_opt_in')).toBeNull()
    expect(tid('social.editor.show_avatar')).not.toBeNull()
  })

  it('lists follow requests and blocked people', async () => {
    api.listFollowRequests.mockResolvedValue({ requests: [{ handle: 'zed' }] })
    api.listBlocks.mockResolvedValue({ users: [{ handle: 'bad_1' }] })
    api.acceptRequest.mockResolvedValue(null)
    api.unblockUser.mockResolvedValue(null)
    await mount('me')
    await click(tid('social.requests.accept'))
    expect(api.acceptRequest).toHaveBeenCalledWith('tok', 'zed')
    expect(tid('social.requests')).toBeNull()
    await click(tid('social.blocks.unblock'))
    expect(api.unblockUser).toHaveBeenCalledWith('tok', 'bad_1')
  })
})
