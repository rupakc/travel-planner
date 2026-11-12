import { useCallback, useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useAuth } from '../../context/AuthContext'
import { useClientConfig } from '../../hooks/useClientConfig'
import { getNotificationSettings, putNotificationSettings } from '../../services/notificationsApi'
import { emit } from '../../telemetry/client'

// social and quiz have no sender yet: stored by the server, not shown here.
const CATEGORIES = ['price_drops', 'trip_reminders', 'morning_brief', 'weather', 'nearby']
const TIME_RE = /^([01]\d|2[0-3]):[0-5]\d$/
const DEFAULT_QUIET = { enabled: false, start: '22:00', end: '07:00' }

const track = (name, props) => { try { emit(name, props) } catch { /* telemetry never breaks the UI */ } }

const ROW = 'flex min-h-[44px] flex-wrap items-center justify-between gap-3 py-2'
const INPUT = 'min-h-[44px] rounded-lg border border-slate-300 bg-white px-3 text-sm text-slate-900'
const BTN = 'inline-flex min-h-[44px] min-w-[44px] items-center justify-center rounded-lg border border-slate-300 px-3 text-base font-semibold text-slate-800 hover:bg-slate-50 disabled:opacity-40 focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-500'

function Switch({ checked, onChange, label, tid }) {
  return (
    <button type="button" role="switch" aria-checked={checked} aria-label={label} data-tid={tid}
      onClick={() => onChange(!checked)}
      className="inline-flex min-h-[44px] min-w-[44px] items-center justify-center rounded-lg focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-500">
      <span className={`relative h-6 w-11 rounded-full transition-colors ${checked ? 'bg-teal-700' : 'bg-slate-300'}`}>
        <span aria-hidden="true"
          className={`absolute top-0.5 h-5 w-5 rounded-full bg-white shadow transition-all ${checked ? 'left-[22px]' : 'left-0.5'}`} />
      </span>
    </button>
  )
}

/**
 * Account > Notifications (GET/PUT /api/notification-settings). Renders nothing
 * on a backend without `features.notifications_api`. Every control saves on
 * change and reverts that key if the server refuses.
 */
export default function NotificationsSection() {
  const { t } = useTranslation('notifications')
  const { token } = useAuth()
  const { config, loaded } = useClientConfig()
  const enabled = loaded && Number(config?.features?.notifications_api) >= 1
  const [settings, setSettings] = useState(null)
  const [loadFailed, setLoadFailed] = useState(false)
  const [error, setError] = useState('')
  const alive = useRef(true)
  const inflight = useRef(0)
  useEffect(() => { alive.current = true; return () => { alive.current = false } }, [])

  useEffect(() => {
    if (!token || !enabled) return undefined
    let live = true
    getNotificationSettings(token).then(
      (s) => { if (live) { setSettings(s); track('notif_settings_view', {}) } },
      () => { if (live) setLoadFailed(true) },
    )
    return () => { live = false }
  }, [token, enabled])

  // Optimistic: apply `optimistic` now, send `patch`, adopt the server's answer (when it is the last save in flight), or restore `before`.
  const save = useCallback(async (patch, optimistic, before, onSaved) => {
    setError('')
    setSettings((s) => ({ ...s, ...optimistic }))
    inflight.current += 1
    try {
      const next = await putNotificationSettings(token, patch)
      inflight.current -= 1
      if (!alive.current) return
      // Adopt the server's answer only when no newer save is in flight, or it
      // would roll back an edit made while this one was travelling.
      if (inflight.current === 0 && next && typeof next === 'object') setSettings(next)
      onSaved?.()
    } catch {
      inflight.current -= 1
      if (!alive.current) return
      setSettings((s) => ({ ...s, ...before }))
      setError(t('error.save'))
    }
  }, [token, t])

  if (!token || !enabled) return null
  if (loadFailed) {
    return <p role="status" className="mx-auto mt-6 max-w-2xl text-sm text-slate-600" data-tid="notif.error">{t('error.load')}</p>
  }
  if (!settings) return null

  const cats = settings.categories || {}
  const qh = settings.quiet_hours || DEFAULT_QUIET
  const cap = Number(settings.daily_cap ?? 3)

  const toggleCategory = (name, on) => save(
    { categories: { [name]: { enabled: on } } },
    { categories: { ...cats, [name]: { ...cats[name], enabled: on } } },
    { categories: cats },
    () => track('notif_category_toggle', { category: name, on }),
  )
  const setQuiet = (next) => save(
    { quiet_hours: next }, { quiet_hours: next }, { quiet_hours: qh },
    () => track('notif_quiet_hours_change', { enabled: !!next.enabled }),
  )
  const setTime = (which, v) => { if (TIME_RE.test(v) && v !== qh[which]) setQuiet({ ...qh, [which]: v }) }
  const stepCap = (d) => {
    const n = Math.min(10, Math.max(1, cap + d))
    if (n !== cap) save({ daily_cap: n }, { daily_cap: n }, { daily_cap: cap }, () => track('notif_cap_change', { cap: n }))
  }

  return (
    <section data-tid="notif.section" aria-labelledby="notif-title"
      className="mx-auto mt-6 max-w-2xl rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
      <h2 id="notif-title" className="text-lg font-semibold text-slate-800">{t('title')}</h2>
      <p className="mt-0.5 text-sm text-slate-500">{t('intro')}</p>
      {error && <p role="alert" className="mt-2 text-sm text-red-700" data-tid="notif.error">{error}</p>}

      <div className="mt-2 divide-y divide-slate-100">
        {CATEGORIES.map((c) => (
          <div key={c} className={ROW}>
            <span className="min-w-0 max-w-[75%] text-sm font-semibold text-slate-800">
              {t(`categories.${c}.label`)}
              <span className="mt-0.5 block text-xs font-normal text-slate-500">{t(`categories.${c}.hint`)}</span>
            </span>
            <Switch checked={cats[c]?.enabled !== false} label={t(`categories.${c}.label`)}
              tid={`notif.category.${c}`} onChange={(v) => toggleCategory(c, v)} />
          </div>
        ))}

        <div className={ROW}>
          <span className="min-w-0 max-w-[75%] text-sm font-semibold text-slate-800">
            {t('quiet.label')}
            <span className="mt-0.5 block text-xs font-normal text-slate-500">{t('quiet.hint')}</span>
          </span>
          <Switch checked={!!qh.enabled} label={t('quiet.label')} tid="notif.quiet.toggle"
            onChange={(v) => setQuiet({ ...qh, enabled: v })} />
        </div>
        {qh.enabled && (
          <div className={ROW}>
            <label className="flex items-center gap-2 text-sm text-slate-800">
              {t('quiet.start')}
              <input type="time" className={INPUT} data-tid="notif.quiet.start" value={qh.start}
                onChange={(e) => setTime('start', e.target.value)} />
            </label>
            <label className="flex items-center gap-2 text-sm text-slate-800">
              {t('quiet.end')}
              <input type="time" className={INPUT} data-tid="notif.quiet.end" value={qh.end}
                onChange={(e) => setTime('end', e.target.value)} />
            </label>
          </div>
        )}
        {qh.enabled && (settings.timezone
          ? <p className="py-1 text-xs text-slate-500" data-tid="notif.quiet.timezone">{t('quiet.timezone', { tz: settings.timezone })}</p>
          : <p className="py-2 text-sm text-amber-800" data-tid="notif.quiet.no_timezone">{t('quiet.noTimezone')}</p>)}

        <div className="py-2">
          <p id="notif-cap-label" className="text-sm font-semibold text-slate-800">{t('cap.label')}</p>
          <p className="text-xs text-slate-500">{t('cap.hint')}</p>
          <div className="mt-1 flex items-center gap-1" role="group" aria-labelledby="notif-cap-label">
            <button type="button" className={BTN} data-tid="notif.cap.dec" aria-label={t('cap.less')}
              disabled={cap <= 1} onClick={() => stepCap(-1)}>−</button>
            <output className="min-w-[2rem] text-center text-sm tabular-nums text-slate-900" data-tid="notif.cap.value"
              aria-label={t('cap.value', { count: cap })}>{cap}</output>
            <button type="button" className={BTN} data-tid="notif.cap.inc" aria-label={t('cap.more')}
              disabled={cap >= 10} onClick={() => stepCap(1)}>+</button>
          </div>
        </div>
      </div>

      {Number(settings.devices) === 0 && (
        <p className="mt-3 rounded-lg bg-slate-50 p-3 text-sm text-slate-600" data-tid="notif.no_devices">{t('noDevices')}</p>
      )}
    </section>
  )
}
