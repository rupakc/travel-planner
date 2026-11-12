// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { MemoryRouter } from 'react-router-dom'

vi.mock('../../context/AuthContext', () => ({ useAuth: () => ({ token: 'tok' }) }))
vi.mock('../../telemetry/client', () => ({ emit: vi.fn() }))
vi.mock('../../services/socialApi', () => ({
  likeIdea: vi.fn(), unlikeIdea: vi.fn(), saveIdea: vi.fn(), deleteIdea: vi.fn(),
  listComments: vi.fn(), addComment: vi.fn(), deleteComment: vi.fn(), markHelpful: vi.fn(), unmarkHelpful: vi.fn(),
  sendReport: vi.fn(),
}))

import { initI18n } from '../../i18n/index'
import { emit } from '../../telemetry/client'
import * as api from '../../services/socialApi'
import IdeaCard from './IdeaCard'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

const HOSTILE = [
  '<img src=x onerror="window.__pwned=1">',
  '<script>window.__pwned=1</script>',
  '[click](javascript:alert(1)) https://evil.example/a',
  '<b>bold</b> **md**',
]

const idea = (over = {}) => ({
  id: 7, kind: 'plan', title: HOSTILE[0], caption: HOSTILE[1],
  author: { handle: HOSTILE[3] },
  snapshot: { destinations: [HOSTILE[2]], days: 5, stats: [{ key: 'activities', count: 4 }], items: { activities: [{ name: HOSTILE[0] }, { name: HOSTILE[3] }] } },
  likes: 2, saves: 1, comments: 1, liked: false, saved: false, mine: false, status: 'published', created_at: '2026-11-01T00:00:00Z',
  ...over,
})

let container, root
const tid = (id) => container.querySelector(`[data-tid="${id}"]`)
const click = async (el) => { await act(async () => { el.dispatchEvent(new MouseEvent('click', { bubbles: true })) }) }
const mount = async (props) => {
  await act(async () => { root.render(<MemoryRouter><IdeaCard idea={idea()} {...props} /></MemoryRouter>) })
}

beforeEach(async () => {
  await initI18n({ lng: 'en', bundleAll: true })
  vi.clearAllMocks()
  window.__pwned = undefined
  container = document.createElement('div'); document.body.appendChild(container); root = createRoot(container)
})
afterEach(() => { act(() => root.unmount()); container.remove() })

describe('IdeaCard plain-text rendering', () => {
  it('shows hostile title, caption, names and handle as literal text, never as elements', async () => {
    api.listComments.mockResolvedValue({
      comments: [{ id: 1, author: { handle: '<img src=x onerror=1>' }, text: HOSTILE[0], helpful: false, mine: false }], next: null,
    })
    await mount({ expanded: true })
    expect(tid('social.idea.title').textContent).toBe(HOSTILE[0])
    expect(tid('social.idea.caption').textContent).toBe(HOSTILE[1])
    expect(tid('social.idea.items').textContent).toContain(HOSTILE[0])
    expect(tid('social.comment.text').textContent).toBe(HOSTILE[0])
    // No element was created from any of it, no link was made from the text.
    expect(container.querySelector('img')).toBeNull()
    expect(container.querySelector('script')).toBeNull()
    expect(container.querySelector('b')).toBeNull()
    expect(container.querySelector('a[href^="javascript"]')).toBeNull()
    expect(container.querySelector('a[href*="evil"]')).toBeNull()
    expect(container.innerHTML).toContain('&lt;img src=x onerror=')
    expect(window.__pwned).toBeUndefined()
  })

  it('does not build a profile link out of a malformed handle', async () => {
    await mount()
    expect(tid('social.idea.author')).toBeNull() // rendered as a plain span, not a link
    expect(container.textContent).toContain(`@${HOSTILE[3]}`)
  })

  it('links a well-formed handle', async () => {
    await mount({ idea: idea({ author: { handle: 'ann_9' } }) })
    expect(tid('social.idea.author').getAttribute('href')).toBe('/u/ann_9')
  })

  it('only accepts an own-origin or https avatar URL', async () => {
    await mount({ idea: idea({ author: { handle: 'ann', avatar_url: 'javascript:alert(1)' } }) })
    expect(container.querySelector('img')).toBeNull()
    await mount({ idea: idea({ author: { handle: 'ann', avatar_url: '/api/avatars/1.png' } }) })
    expect(container.querySelector('img').getAttribute('src')).toBe('/api/avatars/1.png')
  })
})

describe('IdeaCard actions', () => {
  it('likes optimistically, reports telemetry without ids, and rolls back on failure', async () => {
    const onChange = vi.fn()
    api.likeIdea.mockResolvedValue(null)
    await mount({ onChange })
    await click(tid('social.idea.like'))
    expect(api.likeIdea).toHaveBeenCalledWith('tok', 7)
    expect(onChange).toHaveBeenLastCalledWith(expect.objectContaining({ liked: true, likes: 3 }))
    expect(emit).toHaveBeenCalledWith('social_idea_like', { on: true })

    api.likeIdea.mockRejectedValue({ status: 429, code: 'limit_reached', detail: '' })
    await click(tid('social.idea.like'))
    expect(onChange).toHaveBeenLastCalledWith(expect.objectContaining({ liked: false, likes: 2 }))
    expect(tid('social.idea.error').textContent).toBe("You have reached today's limit. Try again tomorrow.")
  })

  it('saves to my plans, with telemetry', async () => {
    api.saveIdea.mockResolvedValue({ plan_id: 3 })
    await mount()
    await click(tid('social.idea.save'))
    expect(api.saveIdea).toHaveBeenCalledWith('tok', 7)
    expect(tid('social.idea.notice').textContent).toBe('Saved to your plans.')
    expect(emit).toHaveBeenCalledWith('social_idea_save', undefined)
  })

  it('hides save and report on my own idea and offers a confirmed delete', async () => {
    const onDeleted = vi.fn()
    api.deleteIdea.mockResolvedValue(null)
    await mount({ idea: idea({ mine: true, author: { handle: 'me_x' } }), onDeleted })
    expect(tid('social.idea.save')).toBeNull()
    expect(tid('social.idea.report')).toBeNull()
    await click(tid('social.idea.delete'))
    expect(api.deleteIdea).not.toHaveBeenCalled()
    await click(tid('social.idea.deleteYes'))
    expect(onDeleted).toHaveBeenCalledWith(7)
  })

  it('reports an idea with an enum reason', async () => {
    api.sendReport.mockResolvedValue(null)
    await mount()
    await click(tid('social.idea.report'))
    await click(tid('social.report.submit'))
    expect(api.sendReport).toHaveBeenCalledWith('tok', { target: 'idea', id: '7', reason: 'spam' })
    expect(emit).toHaveBeenCalledWith('social_report', { target: 'idea', reason: 'spam' })
    expect(tid('social.report.sent')).not.toBeNull()
  })

  it('posts a comment and counts it', async () => {
    api.listComments.mockResolvedValue({ comments: [], next: null })
    api.addComment.mockResolvedValue({ id: 9, author: { handle: 'ann' }, text: 'Nice <b>one</b>', helpful: false, mine: true })
    const onChange = vi.fn()
    await mount({ expanded: true, onChange })
    const input = tid('social.comments.input')
    await act(async () => {
      Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set.call(input, 'Nice <b>one</b>')
      input.dispatchEvent(new Event('input', { bubbles: true }))
    })
    await click(tid('social.comments.post'))
    expect(api.addComment).toHaveBeenCalledWith('tok', 7, 'Nice <b>one</b>')
    expect(tid('social.comment.text').textContent).toBe('Nice <b>one</b>')
    expect(container.querySelector('b')).toBeNull()
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ comments: 2 }))
    expect(emit).toHaveBeenCalledWith('social_comment', undefined)
  })
})
