// @vitest-environment jsdom
import { describe, it, expect, afterEach, vi } from 'vitest'
import { act } from 'react'
import { createRoot } from 'react-dom/client'

const journey = vi.hoisted(() => ({ value: { enabled: true } }))
vi.mock('../../hooks/useJourney', () => ({ useJourney: () => journey.value }))
vi.mock('../../telemetry/client', () => ({ emit: vi.fn() }))

import '../../i18n'
import { emit } from '../../telemetry/client'
import CompletenessMeter from './CompletenessMeter'

globalThis.IS_REACT_ACT_ENVIRONMENT = true
let container, root
function render(props) {
  container = document.createElement('div'); document.body.appendChild(container)
  root = createRoot(container)
  act(() => root.render(<CompletenessMeter {...props} />))
}
afterEach(() => { act(() => root.unmount()); container.remove(); vi.clearAllMocks(); journey.value = { enabled: true } })

describe('CompletenessMeter', () => {
  it('shows the checklist and emits once', () => {
    render({ selections: { hotel: {} }, searchData: {}, visaChecked: true, surface: 'trip' })
    expect(container.querySelectorAll('[data-done="true"]').length).toBe(2)
    expect(container.querySelectorAll('li').length).toBe(5)
    act(() => root.render(<CompletenessMeter selections={{ hotel: {} }} searchData={{}} visaChecked surface="trip" />))
    expect(emit).toHaveBeenCalledTimes(1)
    expect(emit).toHaveBeenCalledWith('completeness_view', { surface: 'trip', percent: 40 })
  })
  it('renders nothing with the journey off', () => {
    journey.value = { enabled: false }
    render({})
    expect(container.innerHTML).toBe('')
    expect(emit).not.toHaveBeenCalled()
  })
})
