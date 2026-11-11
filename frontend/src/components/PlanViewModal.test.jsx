// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { act } from 'react'
import { createRoot } from 'react-dom/client'

vi.mock('./alerts/WatchFareButton', () => ({ default: () => null }))
vi.mock('./alerts/WatchTripButton', () => ({ default: () => null }))
vi.mock('./PlanExport', () => ({ default: () => null }))

import PlanViewModal from './PlanViewModal'

globalThis.IS_REACT_ACT_ENVIRONMENT = true
let container, root

const PLAN = {
  id: 3,
  name: 'Lisbon in spring',
  search_data: { origin: 'NYC', destination: 'Lisbon', departure_date: '2027-04-01', return_date: '2027-04-08' },
  selections: { hotel: { name: 'Casa Azul', price_per_night: 120 } },
}

async function render(el) {
  await act(async () => root.render(el))
}

beforeEach(() => {
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
})
afterEach(() => {
  act(() => root.unmount())
  container.remove()
})

const tid = (id) => container.querySelector(`[data-tid="${id}"]`)

describe('PlanViewModal', () => {
  it('as a modal (unchanged): the fixed overlay with the backdrop, the close buttons and Delete', async () => {
    const onClose = vi.fn()
    await render(<PlanViewModal plan={PLAN} token="tok" onClose={onClose} />)
    expect(container.querySelector('.fixed.inset-0')).not.toBeNull()
    expect(tid('plan.modal-close-x')).not.toBeNull()
    expect(tid('plan.modal-close')).not.toBeNull()
    expect(tid('plan.delete')).not.toBeNull()
    expect(tid('plan.name-input')).not.toBeNull()
    await act(async () => container.querySelector('.backdrop-blur-sm').click())
    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it('inline: no dialog role, no backdrop, no close button; the plan body and Save stay', async () => {
    await render(<PlanViewModal plan={PLAN} token="tok" inline />)
    expect(container.querySelector('[role="dialog"]')).toBeNull()
    expect(container.querySelector('[aria-modal]')).toBeNull()
    expect(container.querySelector('.backdrop-blur-sm')).toBeNull()
    expect(tid('plan.modal-close-x')).toBeNull()
    expect(tid('plan.modal-close')).toBeNull()
    expect(container.querySelector('.fixed')).toBeNull()
    await act(async () => tid('plan.section-hotel').click())
    expect(container.textContent).toContain('Casa Azul')
    expect(tid('plan.save')).not.toBeNull()
  })

  it('inline: the trip screen owns the title and Delete', async () => {
    await render(<PlanViewModal plan={PLAN} token="tok" inline />)
    expect(tid('plan.name-input')).toBeNull()
    expect(tid('plan.delete')).toBeNull()
  })
})
