// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { act } from 'react'
import { createRoot } from 'react-dom/client'

const cfg = vi.hoisted(() => ({ value: {} }))
vi.mock('../../hooks/useClientConfig', () => ({ useClientConfig: () => ({ config: cfg.value, loaded: true }) }))
vi.mock('../share/ShareDialog', () => ({ default: ({ kind, sessionId }) => <div data-tid="dlg" data-kind={kind} data-session={sessionId} /> }))

import { initI18n } from '../../i18n/index'
import QuizResult from './QuizResult'

globalThis.IS_REACT_ACT_ENVIRONMENT = true
let container, root
const tid = (id) => container.querySelector(`[data-tid="${id}"]`)
const show = async (props) => { await act(async () => root.render(<QuizResult summary={{ score: 100, correct: 1, total: 5 }} onClose={() => {}} {...props} />)) }

beforeEach(async () => {
  await initI18n({ lng: 'en' })
  container = document.createElement('div'); document.body.appendChild(container); root = createRoot(container)
})
afterEach(() => { act(() => root.unmount()); container.remove() })

describe('QuizResult share', () => {
  it('opens the quiz share dialog with the session id when sharing and play are on', async () => {
    cfg.value = { features: { sharing: 1, play: 1 } }
    await show({ sessionId: 's1' })
    await act(async () => { tid('play.result.share').dispatchEvent(new MouseEvent('click', { bubbles: true })) })
    expect(tid('dlg').dataset).toMatchObject({ kind: 'quiz', session: 's1' })
  })
  it.each([
    [{ features: { play: 1 } }, 's1'],
    [{ features: { sharing: 1 } }, 's1'],
    [{}, 's1'],
    [{ features: { sharing: 1, play: 1 } }, undefined],
  ])('hides the button for %j', async (c, sessionId) => {
    cfg.value = c
    await show({ sessionId })
    expect(tid('play.result.share')).toBeNull()
  })
})
