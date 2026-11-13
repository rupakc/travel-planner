// @vitest-environment jsdom
import { describe, it, expect, vi, afterEach } from 'vitest'
import { act } from 'react'
import { createRoot } from 'react-dom/client'

const cfg = vi.hoisted(() => ({ value: { config: { features: { social: 1 } }, loaded: true } }))
vi.mock('./useClientConfig', () => ({ useClientConfig: () => cfg.value }))
const st = vi.hoisted(() => ({ value: {} }))
vi.mock('../components/account/SettingsSync', () => ({
  useAccountSettings: () => ({ settings: st.value }),
  useSettingsLoading: () => false,
}))
import { useSocialEnabled } from './useSocial'

globalThis.IS_REACT_ACT_ENVIRONMENT = true
let out
function Probe() { out = useSocialEnabled(); return null }
const run = async () => {
  const el = document.createElement('div')
  const root = createRoot(el)
  await act(async () => root.render(<Probe />))
  await act(async () => root.unmount())
}
afterEach(() => { st.value = {} })

describe('useSocialEnabled and hide_community', () => {
  it('is on when the key is missing (older backend)', async () => {
    st.value = {}
    await run()
    expect(out.enabled).toBe(true)
  })
  it('is off when hide_community is true', async () => {
    st.value = { hide_community: true }
    await run()
    expect(out.enabled).toBe(false)
  })
})
