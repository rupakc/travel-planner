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
import RejectedWrites, { useRejectedWrites } from '../offline/RejectedWrites'

const num = (s) => Number(s)
const card = 'rounded-xl border border-slate-200 bg-white p-4'

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
  const rejected = useRejectedWrites(uid, trip?.id == null ? null : `/trips/${trip.id}/expenses`)
  const keyRef = useRef(storeKey)
  keyRef.current = storeKey // in-flight work compares its captured key with this
  const tripId = trip?.id
  const today = localToday()

  const load = useCallback(async () => {
    try {
      const res = await listExpenses(token, tripId)
      if (keyRef.current !== storeKey) return // the user switched trip meanwhile
      setData(res)
      setFailed(false)
      const seen = new Set(res.expenses.map((e) => e.client_id))
      setPending((p) => p.filter((e) => !seen.has(e.client_id)))
    } catch {
      if (keyRef.current === storeKey) setFailed(true)
    }
  }, [token, tripId, storeKey])

  useEffect(() => {
    if (!enabled || tripId == null) return
    if (online) load()
  }, [enabled, tripId, online, load])

  useEffect(() => { writePending(storeKey, pending) }, [storeKey, pending])
  // A write the server refused (trip cap) is no longer "waiting": the notice below replaces its row.
  useEffect(() => {
    if (!rejected.length) return
    const gone = new Set(rejected.map((r) => r.body?.client_id))
    setPending((p) => (p.some((e) => gone.has(e.client_id)) ? p.filter((e) => !gone.has(e.client_id)) : p))
  }, [rejected])

  const defaultCurrency = data?.rate?.local || 'USD'

  const queue = async (body) => {
    const row = { id: `pending-${body.client_id}`, ...body, note: body.note || '', pending: true }
    const key = storeKey
    if (keyRef.current === key) setPending((p) => [...p, row])
    else writePending(key, [...readPending(key), row]) // switched away: file it under its own trip
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
      <h2 className="text-lg font-semibold text-slate-900">{t('title')}</h2>

      <div className={card}>
        <ExpenseForm defaultCurrency={defaultCurrency} today={today} busy={busy} onSubmit={add} />
        {formError && !editing && <p role="alert" className="mt-2 text-sm text-red-700">{formError}</p>}
      </div>

      <RejectedWrites userId={uid} rows={rejected}
        summary={(b) => (b ? `${money(b.amount, b.currency)} · ${t(`cat.${b.category}`, { defaultValue: '' })}` : '')} />

      {failed && !data && (
        <p className="text-sm text-slate-600">
          {t('loadFailed')}{' '}
          <button type="button" data-tid="expense-retry" onClick={load}
            className="min-h-[44px] underline text-teal-700">{t('retry')}</button>
        </p>
      )}

      {totals && (
        <div className={card} data-tid="expense-totals">
          <h3 className="text-sm font-semibold text-slate-700 mb-2">{t('totals')}</h3>
          <ul className="text-sm text-slate-800 space-y-1">
            {Object.entries(totals.by_currency || {}).map(([cur, amt]) => (
              <li key={cur} data-tid={`expense-total-${cur}`}>{money(amt, cur)}</li>
            ))}
          </ul>
          {usd != null && budget > 0 && (
            <div className="mt-3" data-tid="expense-budget">
              <p className="text-sm text-slate-800">
                {t('budget', { usd: money(usd, 'USD'), budget: money(budget, 'USD') })}
              </p>
              <div className="mt-1 h-2 rounded-full bg-slate-200" role="progressbar"
                aria-valuemin={0} aria-valuemax={100} aria-valuenow={pct}>
                <div className="h-2 rounded-full bg-teal-700" style={{ width: `${pct}%` }} />
              </div>
              {data.rate?.as_of && (
                <p className="mt-1 text-xs text-slate-600">
                  {t('rateNote', { date: fmtDate(data.rate.as_of, { day: 'numeric', month: 'short' }) })}
                </p>
              )}
            </div>
          )}
          {totals.unconverted?.length > 0 && (
            <p className="mt-2 text-xs text-slate-600" data-tid="expense-unconverted">
              {t('unconverted', { list: totals.unconverted.join(', ') })}
            </p>
          )}
        </div>
      )}

      {byDay.length === 0 && data && (
        <p className="text-sm text-slate-600">{t('empty')}</p>
      )}

      {byDay.map(([day, items]) => (
        <div key={day} data-tid={`expense-day-${day}`}>
          <h3 className="text-sm font-semibold text-slate-700 mb-1">
            {fmtDate(`${day}T12:00:00`, { weekday: 'short', day: 'numeric', month: 'short' })}
          </h3>
          <ul className="divide-y divide-slate-200 rounded-xl border border-slate-200 bg-white">
            {items.map((e) => (
              <li key={e.id} className="p-3" data-tid={`expense-row-${e.id}`}>
                {editing?.id === e.id ? (
                  <>
                    <ExpenseForm initial={e} defaultCurrency={defaultCurrency} today={today} busy={busy}
                      onSubmit={save} onCancel={() => setEditing(null)} />
                    {formError && <p role="alert" className="mt-2 text-sm text-red-700">{formError}</p>}
                  </>
                ) : (
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <p className="text-sm font-medium text-slate-900">
                        {money(e.amount, e.currency)} · {t(`cat.${e.category}`)}
                      </p>
                      {e.note && <p className="text-sm text-slate-600 break-words">{e.note}</p>}
                      {e.pending && (
                        <p className="text-xs text-amber-800" data-tid="expense-pending">{t('waiting')}</p>
                      )}
                    </div>
                    {!e.pending && (
                      <div className="flex shrink-0 gap-1">
                        <button type="button" data-tid={`expense-edit-${e.id}`} disabled={!online}
                          title={online ? undefined : t('needsConnection')}
                          onClick={() => { setFormError(null); setEditing(e) }}
                          className="min-h-[44px] px-3 text-sm text-teal-700 disabled:opacity-50">{t('edit')}</button>
                        <button type="button" data-tid={`expense-delete-${e.id}`} disabled={!online}
                          title={online ? undefined : t('needsConnection')}
                          onClick={() => remove(e)}
                          className="min-h-[44px] px-3 text-sm text-red-700 disabled:opacity-50">{t('delete')}</button>
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
