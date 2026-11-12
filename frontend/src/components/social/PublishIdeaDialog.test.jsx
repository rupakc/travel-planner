// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { MemoryRouter } from 'react-router-dom'

const cfg = vi.hoisted(() => ({ config: { features: { social: 1 } }, loaded: true }))
vi.mock('../../hooks/useClientConfig', () => ({ useClientConfig: () => cfg }))
vi.mock('../../context/AuthContext', () => ({ useAuth: () => ({ token: 'tok' }) }))
vi.mock('../../telemetry/client', () => ({ emit: vi.fn() }))
vi.mock('../../services/socialApi', () => ({ getOwnProfile: vi.fn(), publishIdea: vi.fn() }))

import { initI18n } from '../../i18n/index'
import { emit } from '../../telemetry/client'
import { getOwnProfile, publishIdea } from '../../services/socialApi'
import PublishIdeaButton from './PublishIdeaButton'

globalThis.IS_REACT_ACT_ENVIRONMENT = true
let container, root
const tid = (id) => document.querySelector(`[data-tid="${id}"]`)
const click = async (el) => { await act(async () => { el.dispatchEvent(new MouseEvent('click', { bubbles: true })) }) }
const type = async (el, value) => {
  const proto = el.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype
  await act(async () => {
    Object.getOwnPropertyDescriptor(proto, 'value').set.call(el, value)
    el.dispatchEvent(new Event('input', { bubbles: true }))
  })
}
const mount = async (kind = 'plan') => {
  await act(async () => { root.render(<MemoryRouter><PublishIdeaButton kind={kind} planId={12} /></MemoryRouter>) })
}

beforeEach(async () => {
  await initI18n({ lng: 'en', bundleAll: true })
  vi.clearAllMocks()
  cfg.config = { features: { social: 1 } }
  container = document.createElement('div'); document.body.appendChild(container); root = createRoot(container)
})
afterEach(() => { act(() => root.unmount()); container.remove() })

describe('PublishIdeaButton', () => {
  it('renders nothing when the server has no social feed', async () => {
    cfg.config = { features: {} }
    await mount()
    expect(container.innerHTML).toBe('')
    cfg.config = { features: { social: 0 } }
    await mount()
    expect(container.innerHTML).toBe('')
  })

  it('asks for a profile first when there is none', async () => {
    getOwnProfile.mockResolvedValue({ handle: null, visibility: 'private' })
    await mount()
    await click(tid('social.publish.open.plan'))
    expect(tid('social.publish.needProfile')).not.toBeNull()
    expect(tid('social.publish.submit')).toBeNull()
  })

  it('asks to un-private a private profile', async () => {
    getOwnProfile.mockResolvedValue({ handle: 'ann', visibility: 'private' })
    await mount()
    await click(tid('social.publish.open.plan'))
    expect(tid('social.publish.private')).not.toBeNull()
  })

  it('publishes with the plan id and reports only the kind', async () => {
    getOwnProfile.mockResolvedValue({ handle: 'ann', visibility: 'public' })
    publishIdea.mockResolvedValue({ id: 1, status: 'published' })
    await mount('recap')
    await click(tid('social.publish.open.recap'))
    await type(tid('social.publish.title'), 'Lisbon in 3 days')
    await type(tid('social.publish.caption'), 'Pastel de nata <b>x</b>')
    await click(tid('social.publish.submit'))
    expect(publishIdea).toHaveBeenCalledWith('tok', expect.objectContaining({
      plan_id: 12, kind: 'recap', title: 'Lisbon in 3 days', caption: 'Pastel de nata <b>x</b>',
    }))
    expect(emit).toHaveBeenCalledWith('social_idea_publish', { kind: 'recap' })
    expect(tid('social.publish.done').textContent).toMatch(/Published/)
  })

  it('says a held idea waits for review, and shows server errors', async () => {
    getOwnProfile.mockResolvedValue({ handle: 'ann', visibility: 'followers' })
    publishIdea.mockResolvedValueOnce({ id: 1, status: 'held' })
    await mount()
    await click(tid('social.publish.open.plan'))
    await type(tid('social.publish.title'), 'T')
    await click(tid('social.publish.submit'))
    expect(tid('social.publish.done').textContent).toMatch(/review/)
  })

  it('maps an error code to translated text', async () => {
    getOwnProfile.mockResolvedValue({ handle: 'ann', visibility: 'public' })
    publishIdea.mockRejectedValue({ status: 403, code: 'email_unverified', detail: 'x' })
    await mount()
    await click(tid('social.publish.open.plan'))
    await type(tid('social.publish.title'), 'T')
    await click(tid('social.publish.submit'))
    expect(tid('social.publish.error').textContent).toBe('Verify your email address to post.')
  })

  it('closes on Escape', async () => {
    getOwnProfile.mockResolvedValue({ handle: 'ann', visibility: 'public' })
    await mount()
    await click(tid('social.publish.open.plan'))
    expect(tid('social.publish')).not.toBeNull()
    await act(async () => { window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true })) })
    expect(tid('social.publish')).toBeNull()
  })
})
