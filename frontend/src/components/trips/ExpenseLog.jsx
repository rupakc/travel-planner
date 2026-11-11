import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useJourney } from '../../hooks/useJourney'
import { useAuth } from '../../context/AuthContext'
import { useOnline } from '../../offline/useOnline'
import { enqueue } from '../../offline/outbox'
import { addExpense, deleteExpense, listExpenses, updateExpense } from '../../services/tripsApi'
import { emit } from '../../telemetry/client'
import { fmtCurrency, fmtDate } from '../../i18n/format'
import { localToday } from '../../utils/tripPhase'
import ExpenseForm from './ExpenseForm'

const num = (s) => Number(s)
const card = 'rounded-xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 p-4'

// The outbox has no way to list its items, so queued rows are mirrored in
// sessionStorage (per user and trip) to survive a remount or reload.
const pendingKey = (uid, tripId) => `tp_exp_pending:${uid}:${tripId}`
function readPending(key) {
  try { const v = JSON.parse(sessionStorage.getItem(key)); return Array.isArray(v) ? v : [] } catch { return [] }
}
function writePending(key, rows) {
  try {
    if (rows.length) sessionStorage.setItem(key, JSON.stringify(rows)); else sessionStorage.removeItem(key)
  } catch { /* storage unavailable */ }
}

function newClientId() {
  try { return crypto.randomUUID() } catch { return `${Date.now()}-${Math.random().toString(16).slice(2)}` }
}

// Expense log for one trip: quick add, list by day, totals per currency and an
// estimated share of the budget. Offline or on a network error an entry is
// queued in the outbox with a client_id and shown as "Waiting to sync".
export default function ExpenseLog({ trip, token }) {
  const { enabled } = useJourney()
  const { t } = useTranslation('expenses')
  const { user } = useAuth()
  const online = useOnline()
  const [data, setData] = useState(null) // {expenses, totals, rate}
  const uid = user?.id ?? user?.username
  const storeKey = pendingKey(uid, trip?.id)
  const [pending, setPending] = useState(() => readPending(storeKey)) // queued, not yet on the server
  const savingRef = useRef(false)
  const [failed, setFailed] = useState(false)
  const [editing, setEditing] = useState(null)
  const [busy, setBusy] = useState(false)
  const [formError, setFormError] = useState(null)
  const [loadedKey, setLoadedKey] = useState(storeKey)
  if (loadedKey !== storeKey) { // another user or trip: its queued rows, not the old ones
    setLoadedKey(storeKey)
    setPending(readPending(storeKey))
    setData(null)
    setEditing(null)
  }
  const tripId = trip?.id
  const today = localToday()

  const load = useCallback(async () => {
    try {
      const res = await listExpenses(token, tripId)
      setData(res)
      setFailed(false)
      const seen = new Set(res.expenses.map((e) => e.client_id))
      setPending((p) => p.filter((e) => !seen.has(e.client_id)))
    } catch {
      setFailed(true)
    }
  }, [token, tripId])

  useEffect(() => {
    if (!enabled || tripId == null) return
    if (online) load()
  }, [enabled, tripId, online, load])

  useEffect(() => { writePending(storeKey, pending) }, [storeKey, pending])

  const defaultCurrency = data?.rate?.local || 'USD'

  const queue = async (body) => {
    const row = { id: `pending-${body.client_id}`, ...body, note: body.note || '', pending: true }
    setPending((p) => [...p, row])
    await enqueue(uid, {
      method: 'POST', path: `/trips/${tripId}/expenses`, body, key: `expense:${tripId}:${body.client_id}`,
    })
  }

  const add = async (fields) => {
    if (savingRef.current) return false
    savingRef.current = true
    const body = { client_id: newClientId(), ...fields }
    if (!body.note) delete body.note
    setBusy(true)
    setFormError(null)
    let queued = false
    try {
      if (!online) { queued = true; await queue(body) } else {
        try {
          await addExpense(token, tripId, body)
          await load()
        } catch (err) {
          if (err?.code !== 'network') throw err
          queued = true
          await queue(body)
        }
      }
      emit('expense_action', { action: 'add', category: body.category, queued })
      return true
    } catch {
      setFormError(t('saveFailed'))
      return false
    } finally {
      savingRef.current = false
      setBusy(false)
    }
  }

  const save = async (fields) => {
    setBusy(true)
    setFormError(null)
    try {
      await updateExpense(token, tripId, editing.id, fields)
      emit('expense_action', { action: 'edit', category: fields.category, queued: false })
      setEditing(null)
      await load()
      return true
    } catch {
      setFormError(t('saveFailed'))
      return false
    } finally {
      setBusy(false)
    }
  }

  const remove = async (exp) => {
    try {
      await deleteExpense(token, tripId, exp.id)
      emit('expense_action', { action: 'delete', category: exp.category, queued: false })
      await load()
    } catch {
      setFormError(t('saveFailed'))
    }
  }

  const rows = useMemo(() => [...(data?.expenses ?? []), ...pending], [data, pending])
  const byDay = useMemo(() => {
    const groups = new Map()
    for (const e of rows) {
      if (!groups.has(e.spent_on)) groups.set(e.spent_on, [])
      groups.get(e.spent_on).push(e)
    }
    return [...groups.entries()].sort((a, b) => (a[0] < b[0] ? 1 : -1))
  }, [rows])

  if (!enabled || tripId == null) return null

  const totals = data?.totals
  const budget = num(trip?.budget_usd)
  const usd = totals?.usd_estimate != null ? num(totals.usd_estimate) : null
  const pct = usd != null && budget > 0 ? Math.min(100, Math.round((usd / budget) * 100)) : 0
  const money = (a, c) => fmtCurrency(num(a), c)

  return (
    <section data-tid="expense-log" className="space-y-4">
      <h2 className="text-lg font-semibold text-slate-900 dark:text-slate-100">{t('title')}</h2>

      <div className={card}>
        <ExpenseForm defaultCurrency={defaultCurrency} today={today} busy={busy} onSubmit={add} />
        {formError && !editing && <p role="alert" className="mt-2 text-sm text-red-700 dark:text-red-300">{formError}</p>}
      </div>

      {failed && !data && (
        <p className="text-sm text-slate-600 dark:text-slate-300">
          {t('loadFailed')}{' '}
          <button type="button" data-tid="expense-retry" onClick={load}
            className="min-h-[44px] underline text-teal-700 dark:text-teal-300">{t('retry')}</button>
        </p>
      )}

      {totals && (
        <div className={card} data-tid="expense-totals">
          <h3 className="text-sm font-semibold text-slate-700 dark:text-slate-200 mb-2">{t('totals')}</h3>
          <ul className="text-sm text-slate-800 dark:text-slate-100 space-y-1">
            {Object.entries(totals.by_currency || {}).map(([cur, amt]) => (
              <li key={cur} data-tid={`expense-total-${cur}`}>{money(amt, cur)}</li>
            ))}
          </ul>
          {usd != null && budget > 0 && (
            <div className="mt-3" data-tid="expense-budget">
              <p className="text-sm text-slate-800 dark:text-slate-100">
                {t('budget', { usd: money(usd, 'USD'), budget: money(budget, 'USD') })}
              </p>
              <div className="mt-1 h-2 rounded-full bg-slate-200 dark:bg-slate-700" role="progressbar"
                aria-valuemin={0} aria-valuemax={100} aria-valuenow={pct}>
                <div className="h-2 rounded-full bg-teal-700 dark:bg-teal-400" style={{ width: `${pct}%` }} />
              </div>
              {data.rate?.as_of && (
                <p className="mt-1 text-xs text-slate-600 dark:text-slate-300">
                  {t('rateNote', { date: fmtDate(data.rate.as_of, { day: 'numeric', month: 'short' }) })}
                </p>
              )}
            </div>
          )}
          {totals.unconverted?.length > 0 && (
            <p className="mt-2 text-xs text-slate-600 dark:text-slate-300" data-tid="expense-unconverted">
              {t('unconverted', { list: totals.unconverted.join(', ') })}
            </p>
          )}
        </div>
      )}

      {byDay.length === 0 && data && (
        <p className="text-sm text-slate-600 dark:text-slate-300">{t('empty')}</p>
      )}

      {byDay.map(([day, items]) => (
        <div key={day} data-tid={`expense-day-${day}`}>
          <h3 className="text-sm font-semibold text-slate-700 dark:text-slate-200 mb-1">
            {fmtDate(`${day}T12:00:00`, { weekday: 'short', day: 'numeric', month: 'short' })}
          </h3>
          <ul className="divide-y divide-slate-200 dark:divide-slate-700 rounded-xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900">
            {items.map((e) => (
              <li key={e.id} className="p-3" data-tid={`expense-row-${e.id}`}>
                {editing?.id === e.id ? (
                  <>
                    <ExpenseForm initial={e} defaultCurrency={defaultCurrency} today={today} busy={busy}
                      onSubmit={save} onCancel={() => setEditing(null)} />
                    {formError && <p role="alert" className="mt-2 text-sm text-red-700 dark:text-red-300">{formError}</p>}
                  </>
                ) : (
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <p className="text-sm font-medium text-slate-900 dark:text-slate-100">
                        {money(e.amount, e.currency)} · {t(`cat.${e.category}`)}
                      </p>
                      {e.note && <p className="text-sm text-slate-600 dark:text-slate-300 break-words">{e.note}</p>}
                      {e.pending && (
                        <p className="text-xs text-amber-800 dark:text-amber-300" data-tid="expense-pending">{t('waiting')}</p>
                      )}
                    </div>
                    {!e.pending && (
                      <div className="flex shrink-0 gap-1">
                        <button type="button" data-tid={`expense-edit-${e.id}`} disabled={!online}
                          title={online ? undefined : t('needsConnection')}
                          onClick={() => { setFormError(null); setEditing(e) }}
                          className="min-h-[44px] px-3 text-sm text-teal-700 dark:text-teal-300 disabled:opacity-50">{t('edit')}</button>
                        <button type="button" data-tid={`expense-delete-${e.id}`} disabled={!online}
                          title={online ? undefined : t('needsConnection')}
                          onClick={() => remove(e)}
                          className="min-h-[44px] px-3 text-sm text-red-700 dark:text-red-300 disabled:opacity-50">{t('delete')}</button>
                      </div>
                    )}
                  </div>
                )}
              </li>
            ))}
          </ul>
        </div>
      ))}
    </section>
  )
}
