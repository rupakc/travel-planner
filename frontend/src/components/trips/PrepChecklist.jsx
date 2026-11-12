import { useCallback, useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Check } from 'lucide-react'
import { getPrep, setPrepItem } from '../../services/tripsApi'
import { useJourney } from '../../hooks/useJourney'
import { announceGame } from '../../game/announce'
import { emit } from '../../telemetry/client'
import { fmtDate } from '../../i18n/format'
import TripReadyBar from './TripReadyBar'

const day = (iso) => fmtDate(`${iso}T12:00:00Z`, { day: 'numeric', month: 'short', timeZone: 'UTC' })

function recount(items) {
  const live = items.filter((i) => i.status !== 'na')
  const done = live.filter((i) => i.status === 'done').length
  const total = live.length
  return { done, total, percent: total ? Math.floor((100 * done) / total) : 0, complete: total > 0 && done === total }
}

function Facts({ item, t }) {
  const f = item.facts || {}
  const lines = []
  if (item.id === 'visa') {
    if (f.visa_type) {
      lines.push(item.due ? t('facts.visa', { visaType: f.visa_type, date: day(item.due) }) : f.visa_type)
    }
    if (f.max_stay_days) lines.push(t('facts.stay', { n: f.max_stay_days }))
    if (f.processing_time) lines.push(t('facts.processing', { text: f.processing_time }))
  } else if (item.id === 'bookings' && 'flight' in f) {
    lines.push(t('facts.bookings', { flight: t(f.flight ? 'facts.yes' : 'facts.no'), hotel: t(f.hotel ? 'facts.yes' : 'facts.no') }))
  } else if (item.id === 'stress_test' && f.score != null) lines.push(t('facts.score', { n: f.score }))
  else if (item.id === 'sim' && f.plan_name) lines.push(t('facts.sim', { name: f.plan_name }))
  else if (item.id === 'money' && f.currency) lines.push(t('facts.money', { code: f.currency }))
  else if (item.id === 'packing' && f.items != null) lines.push(t('facts.packing', { n: f.items }))
  else if (item.id === 'offline_pack') lines.push(f.saved_at ? t('facts.saved', { date: fmtDate(f.saved_at, { day: 'numeric', month: 'short' }) }) : t('facts.notSaved'))
  const url = item.id === 'visa' && /^https?:\/\//.test(f.official_url || '') ? f.official_url : null
  if (!lines.length && !url) return null
  return (
    <div className="mt-1 text-xs text-slate-700 dark:text-slate-300">
      {lines.map((l) => <div key={l}>{l}</div>)}
      {url && (
        <a href={url} target="_blank" rel="noopener noreferrer" data-tid="prep-visa-official"
          className="underline text-teal-800 dark:text-teal-300">{t('facts.official')}</a>
      )}
    </div>
  )
}

function Row({ item, t, onToggle, busy }) {
  const done = item.status === 'done'
  return (
    <li
      data-tid={`prep-item-${item.id}`}
      className={`flex items-start gap-3 rounded-lg border p-3 ${item.overdue && !done
        ? 'border-amber-400 bg-amber-50 dark:border-amber-500 dark:bg-amber-950'
        : 'border-slate-200 bg-white dark:border-slate-700 dark:bg-slate-900'}`}
    >
      {item.auto ? (
        <span aria-hidden="true" className={`mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full ${done ? 'bg-teal-700 text-white' : 'border border-slate-400'}`}>
          {done && <Check size={14} />}
        </span>
      ) : (
        <label className="-m-2 flex h-11 w-11 shrink-0 cursor-pointer items-center justify-center">
          <input
            type="checkbox" checked={done} disabled={item.status === 'na' || busy}
            data-tid={`prep-toggle-${item.id}`}
            aria-label={t(`items.${item.id}.title`)}
            onChange={() => onToggle(item, !done)}
            className="h-5 w-5 accent-teal-700"
          />
        </label>
      )}
      <div className="min-w-0 flex-1">
        <div className={`text-sm font-semibold text-slate-900 dark:text-slate-100 ${done ? 'line-through opacity-70' : ''}`}>
          {t(`items.${item.id}.title`)}
        </div>
        <div className="text-xs text-slate-700 dark:text-slate-300">{t(`items.${item.id}.body`)}</div>
        <Facts item={item} t={t} />
        {item.auto && <div className="mt-1 text-xs italic text-slate-600 dark:text-slate-400">{t('autoNote')}</div>}
        {item.due && !done && item.status !== 'na' && (
          <div className={`mt-1 text-xs font-medium ${item.overdue ? 'text-amber-800 dark:text-amber-300' : 'text-slate-600 dark:text-slate-400'}`}>
            {item.overdue ? `${t('overdue')} · ` : ''}{t('due', { date: day(item.due) })}
          </div>
        )}
      </div>
    </li>
  )
}

export default function PrepChecklist({ trip, token }) {
  const { t } = useTranslation('prep')
  const { enabled } = useJourney()
  const [data, setData] = useState(null)
  const [failed, setFailed] = useState(false)
  const [toast, setToast] = useState(false)
  const [busy, setBusy] = useState(null)
  const [celebrate, setCelebrate] = useState(false)
  const alive = useRef(true)
  const id = trip?.id

  useEffect(() => { alive.current = true; return () => { alive.current = false } }, [])

  const load = useCallback(() => {
    setFailed(false)
    getPrep(token, id).then((d) => { if (alive.current) setData(d) }, () => { if (alive.current) setFailed(true) })
  }, [token, id])
  useEffect(() => { if (enabled && id != null) load() }, [enabled, id, load])

  const toggle = async (item, done) => {
    const before = data
    const items = data.items.map((i) => (i.id === item.id ? { ...i, status: done ? 'done' : 'todo' } : i))
    setData({ ...data, items, ...recount(items) })
    setBusy(item.id)
    setToast(false)
    try {
      const res = await setPrepItem(token, id, item.id, done)
      if (!alive.current) return
      setData(res)
      emit('prep_toggle', { item: item.id, done })
      announceGame(res.game)
      if (res.complete && !before.complete) {
        setCelebrate(true)
        emit('prep_complete', { items: res.total })
      }
    } catch {
      if (alive.current) { setData(before); setToast(true) }
    } finally {
      if (alive.current) setBusy(null)
    }
  }

  if (!enabled) return null
  if (failed) {
    return (
      <div data-tid="prep-error" className="text-sm text-slate-800 dark:text-slate-200">
        {t('error')}{' '}
        <button type="button" data-tid="prep-retry" onClick={load} className="min-h-[44px] rounded-lg bg-teal-700 px-3 text-white hover:bg-teal-800">{t('retry')}</button>
      </div>
    )
  }
  if (!data) return <div data-tid="prep-loading" className="text-sm text-slate-700 dark:text-slate-300">{t('loading')}</div>

  const active = data.items.filter((i) => i.status !== 'na')
  const na = data.items.filter((i) => i.status === 'na')
  return (
    <section data-tid="prep-checklist" aria-label={t('title')} className="space-y-3">
      <h2 className="text-base font-bold text-slate-900 dark:text-slate-100">{t('title')}</h2>
      <TripReadyBar percent={data.percent} complete={data.complete} celebrate={celebrate} />
      <div className="text-xs text-slate-700 dark:text-slate-300">{t('progress', { done: data.done, total: data.total })}</div>
      {toast && <div role="alert" data-tid="prep-toggle-error" className="text-sm text-red-700 dark:text-red-300">{t('toggleFailed')}</div>}
      <ul className="space-y-2">
        {active.map((i) => <Row key={i.id} item={i} t={t} onToggle={toggle} busy={busy === i.id} />)}
      </ul>
      {na.length > 0 && (
        <details data-tid="prep-not-needed" className="rounded-lg border border-slate-200 p-2 dark:border-slate-700">
          <summary data-tid="prep-not-needed-toggle" className="min-h-[44px] cursor-pointer py-2 text-sm font-medium text-slate-800 dark:text-slate-200">
            {t('notNeeded')} ({na.length})
          </summary>
          <ul className="mt-2 space-y-2">
            {na.map((i) => <Row key={i.id} item={i} t={t} onToggle={toggle} busy />)}
          </ul>
        </details>
      )}
    </section>
  )
}
