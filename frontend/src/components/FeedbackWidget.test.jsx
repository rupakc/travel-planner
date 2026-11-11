// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach } from 'vitest'
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { MemoryRouter } from 'react-router-dom'
import { vi } from 'vitest'

vi.mock('../context/AuthContext', () => ({ useAuth: () => ({ token: 't' }) }))

import { initI18n } from '../i18n/index'
import FeedbackWidget from './FeedbackWidget'

globalThis.IS_REACT_ACT_ENVIRONMENT = true
let container, root
beforeEach(async () => {
  await initI18n({ lng: 'en' })
  container = document.createElement('div'); document.body.appendChild(container); root = createRoot(container)
  act(() => root.render(<MemoryRouter><FeedbackWidget /></MemoryRouter>))
})
afterEach(() => {
  act(() => root.unmount()); container.remove()
  document.body.removeAttribute('data-bottom-tabs')
})
const tid = (id) => container.querySelector(`[data-tid="${id}"]`)

describe('FeedbackWidget', () => {
  it('opens the panel on the voyager:open-feedback event', () => {
    expect(tid('feedback.send')).toBeNull()
    act(() => { window.dispatchEvent(new Event('voyager:open-feedback')) })
    expect(tid('feedback.send')).not.toBeNull()
  })
  it('hides the pill on phones and is dark-safe', () => {
    const cls = tid('feedback.toggle').className
    expect(cls).toMatch(/\bhidden\b/)
    expect(cls).toMatch(/\bsm:flex\b/)
    expect(cls).toContain('bg-teal-700')
    expect(cls).not.toContain('slate-700')
  })
  it('sits higher when the bottom tabs are present', async () => {
    expect(tid('feedback.toggle').className).toContain('bottom-6')
    await act(async () => { document.body.setAttribute('data-bottom-tabs', '') })
    expect(tid('feedback.toggle').className).toContain('bottom-20')
    expect(tid('feedback.toggle').className).not.toContain('bottom-6')
  })
})
