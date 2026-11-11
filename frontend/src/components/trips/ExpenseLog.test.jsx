// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { act } from 'react'
import { createRoot } from 'react-dom/client'

let online = true
vi.mock('../../hooks/useJourney', () => ({ useJourney: () => ({ enabled: journeyOn }) }))
vi.mock('../../context/AuthContext', () => ({ useAuth: () => ({ user: { id: 7 } }) }))
vi.mock('../../offline/useOnline', () => ({ useOnline: () => online }))
vi.mock('../../offline/outbox', () => ({ enqueue: vi.fn(async () => {}) }))
vi.mock('../../telemetry/client', () => ({ emit: vi.fn() }))
vi.mock('../../services/tripsApi', () => ({
  listExpenses: vi.fn(), addExpense: vi.fn(), updateExpense: vi.fn(), deleteExpense: vi.fn(),
}))

import * as api from '../../services/tripsApi'
import { enqueue } from '../../offline/outbox'
import { emit } from '../../telemetry/client'
import ExpenseLog from './ExpenseLog'

globalThis.IS_REACT_ACT_ENVIRONMENT = true
let journeyOn = true

const exp = (o) => ({
  id: 1, client_id: 'c1', amount: '12.50', currency: 'EUR', category: 'food', note: 'Lunch',
  spent_on: '2027-04-02', created_at: '', updated_at: '', ...o,
})
const listing = (o = {}) => ({
  expenses: [exp()],
  totals: { by_currency: { EUR: '12.50' }, usd_estimate: '13.59', by_category_usd: {}, unconverted: [] },
  rate: { local: 'EUR', usd_to_local: 0.92, as_of: '2027-04-01T00:00:00Z' },
  ...o,
})

let host, root
const render = async () => {
  await act(async () => { root.render(<ExpenseLog trip={{ id: 12, budget_usd: 1000 }} token="tok" />) })
}
const q = (tid) => host.querySelector(`[data-tid="${tid}"]`)
const type = async (tid, value) => {
  const el = q(tid)
  const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set
  await act(async () => { set.call(el, value); el.dispatchEvent(new Event('input', { bubbles: true })) })
}

beforeEach(() => {
  online = true
  journeyOn = true
  vi.clearAllMocks()
  sessionStorage.clear()
  api.listExpenses.mockResolvedValue(listing())
  host = document.createElement('div')
  document.body.appendChild(host)
  root = createRoot(host)
})
afterEach(() => { act(() => root.unmount()); host.remove() })

describe('ExpenseLog', () => {
  it('renders nothing when the journey is off', async () => {
    journeyOn = false
    await render()
    expect(host.innerHTML).toBe('')
    expect(api.listExpenses).not.toHaveBeenCalled()
  })

  it('queues an add made offline with a client_id and shows Waiting to sync', async () => {
    online = false
    await render()
    await type('expense-amount', '12,50')
    await act(async () => { q('expense-save').click() })
    expect(api.addExpense).not.toHaveBeenCalled()
    expect(enqueue).toHaveBeenCalledTimes(1)
    const [uid, item] = enqueue.mock.calls[0]
    expect(uid).toBe(7)
    expect(item.method).toBe('POST')
    expect(item.path).toBe('/trips/12/expenses')
    expect(item.body.client_id).toMatch(/[0-9a-f-]{36}/)
    expect(item.body.amount).toBe('12.50')
    expect(item.key).toBe(`expense:12:${item.body.client_id}`)
    expect(host.textContent).toContain('Waiting to sync')
    expect(emit).toHaveBeenCalledWith('expense_action', { action: 'add', category: 'food', queued: true })
  })

  it('queues on a network error while online', async () => {
    api.addExpense.mockRejectedValue(Object.assign(new Error('x'), { code: 'network' }))
    await render()
    await type('expense-amount', '5')
    await act(async () => { q('expense-save').click() })
    expect(enqueue).toHaveBeenCalledTimes(1)
    expect(host.textContent).toContain('Waiting to sync')
  })

  it('adds online without queueing and sends no amount in telemetry', async () => {
    api.addExpense.mockResolvedValue(exp({ id: 2 }))
    await render()
    await type('expense-amount', '9.99')
    await act(async () => { q('expense-save').click() })
    expect(api.addExpense).toHaveBeenCalledTimes(1)
    expect(enqueue).not.toHaveBeenCalled()
    expect(JSON.stringify(emit.mock.calls)).not.toContain('9.99')
  })

  it('rejects an invalid amount without saving', async () => {
    await render()
    await type('expense-amount', 'abc')
    await act(async () => { q('expense-save').click() })
    expect(q('expense-error')).not.toBeNull()
    expect(api.addExpense).not.toHaveBeenCalled()
  })

  it('shows the budget bar from usd_estimate, labelled as an estimate', async () => {
    await render()
    const bar = q('expense-budget')
    expect(bar.textContent).toContain('$13.59')
    expect(bar.textContent).toContain('$1,000')
    expect(bar.textContent).toContain('estimate')
    expect(bar.querySelector('[role=progressbar]').getAttribute('aria-valuenow')).toBe('1')
  })

  it('lists unconverted currencies', async () => {
    api.listExpenses.mockResolvedValue(listing({
      totals: { by_currency: { EUR: '12.50', GBP: '4.00' }, usd_estimate: '13.59', by_category_usd: {}, unconverted: ['GBP'] },
    }))
    await render()
    expect(q('expense-unconverted').textContent).toContain('GBP')
    expect(q('expense-total-GBP')).not.toBeNull()
  })

  it('deletes a row', async () => {
    api.deleteExpense.mockResolvedValue(null)
    await render()
    await act(async () => { q('expense-delete-1').click() })
    expect(api.deleteExpense).toHaveBeenCalledWith('tok', 12, 1)
    expect(emit).toHaveBeenCalledWith('expense_action', { action: 'delete', category: 'food', queued: false })
  })

  it('edits a row', async () => {
    api.updateExpense.mockResolvedValue(exp())
    await render()
    await act(async () => { q('expense-edit-1').click() })
    await act(async () => { host.querySelectorAll('[data-tid="expense-save"]')[1].click() })
    expect(api.updateExpense).toHaveBeenCalledTimes(1)
    expect(api.updateExpense.mock.calls[0][2]).toBe(1)
  })

  it('clears the form after an add, so a second tap cannot duplicate it', async () => {
    api.addExpense.mockResolvedValue(exp({ id: 2 }))
    await render()
    await type('expense-amount', '9.99')
    await act(async () => { q('expense-save').click() })
    expect(q('expense-amount').value).toBe('')
    await act(async () => { q('expense-save').click() })
    expect(api.addExpense).toHaveBeenCalledTimes(1)
  })

  it('restores waiting rows after a remount and drops them once the server has them', async () => {
    online = false
    await render()
    await type('expense-amount', '7')
    await act(async () => { q('expense-save').click() })
    const cid = enqueue.mock.calls[0][1].body.client_id
    await act(async () => { root.unmount() })
    root = createRoot(host)
    await render()
    expect(host.textContent).toContain('Waiting to sync')
    online = true
    api.listExpenses.mockResolvedValue(listing({ expenses: [exp({ id: 5, client_id: cid })] }))
    await render()
    expect(host.textContent).not.toContain('Waiting to sync')
    expect(sessionStorage.getItem('tp_exp_pending:7:12')).toBeNull()
  })

  it('disables edit and delete while offline', async () => {
    await render()
    online = false
    await render()
    expect(q('expense-edit-1').disabled).toBe(true)
    expect(q('expense-delete-1').disabled).toBe(true)
  })

  it('keeps typed input when the default currency arrives late', async () => {
    let resolve
    api.listExpenses.mockReturnValue(new Promise((r) => { resolve = r }))
    await render()
    await type('expense-amount', '3')
    await act(async () => { resolve(listing({ rate: { local: 'JPY', usd_to_local: 150, as_of: null } })) })
    expect(q('expense-amount').value).toBe('3')
    expect(q('expense-currency').value).toBe('JPY')
  })

  it('does not leak one trip\'s waiting rows into another', async () => {
    online = false
    await render()
    await type('expense-amount', '7')
    await act(async () => { q('expense-save').click() })
    expect(host.textContent).toContain('Waiting to sync')
    await act(async () => { root.render(<ExpenseLog trip={{ id: 13, budget_usd: 1000 }} token="tok" />) })
    expect(host.textContent).not.toContain('Waiting to sync')
    expect(sessionStorage.getItem('tp_exp_pending:7:12')).not.toBeNull()
    await act(async () => { root.render(<ExpenseLog trip={{ id: 12, budget_usd: 1000 }} token="tok" />) })
    expect(host.textContent).toContain('Waiting to sync')
  })

  it('ignores a slow listing that resolves after a trip switch', async () => {
    let resolveA
    api.listExpenses.mockImplementation((_t, id) => (id === 12
      ? new Promise((r) => { resolveA = r })
      : Promise.resolve(listing({ expenses: [exp({ id: 9, client_id: 'b', note: 'TripB' })] }))))
    await render()
    await act(async () => { root.render(<ExpenseLog trip={{ id: 13, budget_usd: 1000 }} token="tok" />) })
    await act(async () => { resolveA(listing({ expenses: [exp({ id: 8, client_id: 'a', note: 'TripA' })] })) })
    expect(host.textContent).toContain('TripB')
    expect(host.textContent).not.toContain('TripA')
  })

  it('files a row queued after a trip switch under the trip it was made on', async () => {
    online = false
    let release
    enqueue.mockImplementationOnce(() => new Promise((r) => { release = r }))
    await render()
    await type('expense-amount', '7')
    await act(async () => { q('expense-save').click() })
    await act(async () => { root.render(<ExpenseLog trip={{ id: 13, budget_usd: 1000 }} token="tok" />) })
    await act(async () => { release() })
    expect(host.textContent).not.toContain('Waiting to sync')
    expect(JSON.parse(sessionStorage.getItem('tp_exp_pending:7:12'))).toHaveLength(1)
    expect(sessionStorage.getItem('tp_exp_pending:7:13')).toBeNull()
  })
})
