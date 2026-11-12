// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { act } from 'react'
import { createRoot } from 'react-dom/client'

vi.mock('../../context/AuthContext', () => ({ useAuth: () => ({ token: 'tok' }) }))
vi.mock('../../services/api', () => ({ createShare: vi.fn(), revokeShare: vi.fn() }))
const emit = vi.fn()
vi.mock('../../telemetry/client', () => ({ emit: (...a) => emit(...a) }))

import ShareDialog from './ShareDialog'
import { createShare, revokeShare } from '../../services/api'

globalThis.IS_REACT_ACT_ENVIRONMENT = true
const SHARE = { token: 'tok12345', kind: 'plan', url: 'https://v.io/share/tok12345', card_url: { link: '/c/l.png', story: '/c/s.png' }, options: {} }
let root; let host
const render = async (el) => { await act(async () => { root.render(el) }) }
const q = (tid) => host.querySelector(`[data-tid="${tid}"]`)
const click = async (tid) => { await act(async () => { q(tid).dispatchEvent(new MouseEvent('click', { bubbles: true })) }) }
const flush = () => act(async () => { await new Promise((r) => setTimeout(r, 0)) })

beforeEach(() => {
  host = document.createElement('div'); document.body.appendChild(host); root = createRoot(host)
  vi.clearAllMocks(); createShare.mockResolvedValue(SHARE); revokeShare.mockResolvedValue()
})
afterEach(() => { act(() => root.unmount()); host.remove(); vi.unstubAllGlobals() })

describe('ShareDialog', () => {
  it('opens with private defaults, emits share_open, has an accessible dialog', async () => {
    await render(<ShareDialog kind="plan" planId={7} onClose={() => {}} />)
    const d = host.querySelector('[role="dialog"]')
    expect(d.getAttribute('aria-modal')).toBe('true')
    expect(d.getAttribute('aria-labelledby')).toBe('share-title')
    expect(q('share-dates').value).toBe('hidden')
    expect(q('share-origin').checked).toBe(false)
    expect(q('share-name').checked).toBe(false)
    expect(q('share-url')).toBeNull()
    expect(emit).toHaveBeenCalledWith('share_open', { kind: 'plan' })
  })

  it('creates with the chosen options and shows card + link', async () => {
    await render(<ShareDialog kind="plan" planId={7} onClose={() => {}} />)
    await act(async () => { const s = q('share-dates'); s.value = 'month'; s.dispatchEvent(new Event('change', { bubbles: true })) })
    await click('share-name')
    await click('share-create')
    expect(createShare).toHaveBeenCalledWith('tok', { kind: 'plan', plan_id: 7, options: { dates: 'month', show_origin: false, show_name: true } })
    expect(host.querySelector('img').getAttribute('src')).toBe('/c/l.png')
    expect(q('share-url').value).toBe(SHARE.url)
    expect(emit).toHaveBeenCalledWith('share_create', { kind: 'plan', dates: 'month' })
  })

  it('savings sends no plan_id and hides plan-only options', async () => {
    await render(<ShareDialog kind="savings" onClose={() => {}} />)
    expect(q('share-dates')).toBeNull()
    await click('share-create')
    expect(createShare.mock.calls[0][1].plan_id).toBeUndefined()
  })

  it('shows an error and no card when create fails', async () => {
    createShare.mockRejectedValue({ response: { status: 500 } })
    await render(<ShareDialog kind="plan" planId={1} onClose={() => {}} />)
    await click('share-create')
    expect(host.querySelector('[role="alert"]')).not.toBeNull()
    expect(host.querySelector('img')).toBeNull()
  })

  it('shows a loading state while creating', async () => {
    let resolve
    createShare.mockReturnValue(new Promise((r) => { resolve = r }))
    await render(<ShareDialog kind="plan" planId={1} onClose={() => {}} />)
    await click('share-create')
    expect(q('share-create').disabled).toBe(true)
    await act(async () => { resolve(SHARE) })
    expect(q('share-create').disabled).toBe(false)
  })

  it('copies, and falls back to selecting the field when the clipboard refuses', async () => {
    await render(<ShareDialog kind="plan" planId={1} onClose={() => {}} />)
    await click('share-create')
    vi.stubGlobal('navigator', { clipboard: { writeText: vi.fn().mockResolvedValue() } })
    await click('share-copy'); await flush()
    expect(emit).toHaveBeenCalledWith('share_action', { kind: 'plan', target: 'copy' })
    emit.mockClear()
    vi.stubGlobal('navigator', { clipboard: { writeText: vi.fn().mockRejectedValue(new Error('no')) } })
    await click('share-copy'); await flush()
    expect(document.activeElement).toBe(q('share-url'))
    expect(emit).not.toHaveBeenCalledWith('share_action', expect.anything())
  })

  it('opens an intent for whatsapp with noopener', async () => {
    const open = vi.fn(); vi.stubGlobal('open', open)
    await render(<ShareDialog kind="recap" planId={1} onClose={() => {}} />)
    await click('share-create')
    await click('share-whatsapp')
    expect(open.mock.calls[0][0]).toContain('https://wa.me/?text=')
    expect(open.mock.calls[0][2]).toContain('noopener')
    expect(emit).toHaveBeenCalledWith('share_action', { kind: 'recap', target: 'whatsapp' })
  })

  it('revokes after confirmation', async () => {
    const onChange = vi.fn()
    await render(<ShareDialog kind="plan" planId={1} onClose={() => {}} onChange={onChange} />)
    await click('share-create')
    await click('share-revoke')
    expect(revokeShare).not.toHaveBeenCalled()
    await click('share-revoke-yes')
    expect(revokeShare).toHaveBeenCalledWith('tok', 'tok12345')
    expect(emit).toHaveBeenCalledWith('share_revoke', { kind: 'plan' })
    expect(q('share-url')).toBeNull()
    expect(onChange).toHaveBeenLastCalledWith(null)
  })

  it('Escape closes and does not reach other listeners; Tab wraps', async () => {
    const onClose = vi.fn(); const other = vi.fn()
    document.addEventListener('keydown', other)
    await render(<ShareDialog kind="plan" planId={1} onClose={onClose} />)
    await act(async () => { window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true })) })
    expect(onClose).toHaveBeenCalled()
    const last = q('share-close'); last.focus()
    const ev = new KeyboardEvent('keydown', { key: 'Tab', bubbles: true, cancelable: true })
    await act(async () => { window.dispatchEvent(ev) })
    expect(ev.defaultPrevented).toBe(true)
    expect(document.activeElement).not.toBe(last)
    document.removeEventListener('keydown', other)
  })
})
