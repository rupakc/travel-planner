import { useCallback, useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useAuth } from '../../context/AuthContext'
import { getAlertPrefs, putAlertPrefs } from '../../services/alertsApi'
import { patchSettings } from '../../services/accountApi'
import { emit } from '../../telemetry/client'

const KINDS = ['flight', 'hotel', 'activity', 'trip']
const GROUP_OPTIONS = [0, 15, 30, 60]
const DAYS = [1, 2, 3, 4, 5, 6, 7]
const FIELD_OF = {
  digest_weekly: 'digest', digest_day: 'digest', digest_push: 'digest',
  instant: 'instant', quiet_hours: 'quiet_hours', daily_cap: 'cap', group_window_min: 'group',
}
const TIME_RE = /^([01]\d|2[0-3]):[0-5]\d$/

const track = (field) => { try { emit('alert_prefs_change', { field }) } catch { /* never break the UI */ } }
const browserZone = () => {
  try { return Intl.DateTimeFormat().resolvedOptions().timeZone || null } catch { return null }
}

const ROW = 'flex min-h-[44px] flex-wrap items-center justify-between gap-3 py-2'
const INPUT = 'min-h-[44px] rounded-lg border border-slate-300 bg-white px-3 text-sm text-slate-900'
const BTN = 'inline-flex min-h-[44px] min-w-[44px] items-center justify-center rounded-lg border border-slate-300 px-3 text-base font-semibold text-slate-800 hover:bg-slate-50 disabled:opacity-40'

function Switch({ checked, onChange, label, tid }) {
  return (
    <button type="button" role="switch" aria-checked={checked} aria-label={label} data-tid={tid}
      onClick={() => onChange(!checked)}
      className="inline-flex min-h-[44px] min-w-[44px] items-center justify-center">
      <span className={`relative h-6 w-11 rounded-full transition-colors ${checked ? 'bg-teal-700' : 'bg-slate-300'}`}>
        <span className={`absolute top-0.5 h-5 w-5 rounded-full bg-white shadow transition-all ${checked ? 'left-[22px]' : 'left-0.5'}`} />
      </span>
    </button>
  )
}

/**
 * Alert preferences (GET/PUT /alerts/preferences): weekly digest (+ optional
 * push), "targets only", quiet hours, per-category caps and the push grouping
 * window. Every control saves on change and rolls back on error. `timezone` and
 * `quiet_hours_active` are read-only here and never sent.
 */
export default function AlertPrefsPanel() {
  const { t } = useTranslation('alertPrefs')
  const { token } = useAuth()
  const [prefs, setPrefs] = useState(null)
  const [loadFailed, setLoadFailed] = useState(false)
  const [error, setError] = useState('')
  const [busyZone, setBusyZone] = useState(false)
  const alive = useRef(true)
  useEffect(() => { alive.current = true; return () => { alive.current = false } }, [])

  useEffect(() => {
    if (!token) return undefined
    let live = true
    getAlertPrefs(token).then((p) => { if (live) setPrefs(p) }, () => { if (live) setLoadFailed(true) })
    return () => { live = false }
  }, [token])

  // Optimistic save of one writable key; restores that key if the server refuses.
  const save = useCallback(async (key, value) => {
    const before = prefs?.[key]
    setError('')
    setPrefs((p) => ({ ...p, [key]: value }))
    try {
      const next = await putAlertPrefs(token, { [key]: value })
      if (!alive.current) return
      if (next && typeof next === 'object') setPrefs(next)
      track(FIELD_OF[key])
    } catch (err) {
      if (!alive.current) return
      setPrefs((p) => ({ ...p, [key]: before }))
      setError(err?.status === 422 || err?.error_code === 'alert_prefs_invalid' ? t('error.invalid') : t('error.save'))
    }
  }, [prefs, token, t])

  const useBrowserZone = async () => {
    const tz = browserZone()
    if (!tz || busyZone) return
    setBusyZone(true); setError('')
    try {
      await patchSettings(token, { timezone: tz })
      const fresh = await getAlertPrefs(token)
      if (alive.current) setPrefs(fresh)
    } catch {
      if (alive.current) setError(t('error.timezone'))
    } finally {
      if (alive.current) setBusyZone(false)
    }
  }

  if (!token) return null
  if (loadFailed) return <p className="text-sm text-slate-600" data-tid="alert-prefs-error">{t('error.load')}</p>
  if (!prefs) return null

  const qh = prefs.quiet_hours || { enabled: false, start: '22:00', end: '07:00' }
  const caps = prefs.daily_cap || {}
  const zone = browserZone()
  const quietInactive = qh.enabled && (!prefs.timezone || prefs.quiet_hours_active === false)
  const groupValue = Number(prefs.group_window_min ?? 0)
  const groupOptions = GROUP_OPTIONS.includes(groupValue) ? GROUP_OPTIONS : [...GROUP_OPTIONS, groupValue].sort((a, b) => a - b)

  const setTime = (which, v) => { if (TIME_RE.test(v)) save('quiet_hours', { ...qh, [which]: v }) }
  const stepCap = (kind, d) => {
    const n = Math.min(10, Math.max(1, (caps[kind] ?? 3) + d))
    if (n !== caps[kind]) save('daily_cap', { ...caps, [kind]: n })
  }

  return (
    <section className="rounded-xl border border-slate-200 p-4" aria-labelledby="alert-prefs-title" data-tid="alert-prefs">
      <h2 id="alert-prefs-title" className="text-base font-semibold text-slate-900">{t('title')}</h2>
      <p className="text-sm text-slate-600">{t('intro')}</p>
      {error && <p role="alert" className="mt-2 text-sm text-red-700" data-tid="alert-prefs-error">{error}</p>}

      <div className="divide-y divide-slate-100">
        <div className={ROW}>
          <span className="text-sm text-slate-800">{t('digest.label')}</span>
          <Switch checked={!!prefs.digest_weekly} label={t('digest.label')} tid="alert-prefs-digest"
            onChange={(v) => save('digest_weekly', v)} />
        </div>
        {prefs.digest_weekly && (
          <>
            <div className={ROW}>
              <label htmlFor="alert-prefs-day" className="text-sm text-slate-800">{t('digest.day')}</label>
              <select id="alert-prefs-day" className={INPUT} data-tid="alert-prefs-day" value={prefs.digest_day}
                onChange={(e) => save('digest_day', Number(e.target.value))}>
                {DAYS.map((d) => <option key={d} value={d}>{t(`day.${d}`)}</option>)}
              </select>
            </div>
            <div className={ROW}>
              <span className="text-sm text-slate-800">{t('digest.push')}</span>
              <Switch checked={!!prefs.digest_push} label={t('digest.push')} tid="alert-prefs-digest-push"
                onChange={(v) => save('digest_push', v)} />
            </div>
          </>
        )}

        <div className={ROW}>
          <span className="max-w-[70%] text-sm text-slate-800">
            {t('instant.label')}
            <span className="block text-xs text-slate-500">{t('instant.hint')}</span>
          </span>
          <Switch checked={prefs.instant === 'targets_only'} label={t('instant.label')} tid="alert-prefs-instant"
            onChange={(v) => save('instant', v ? 'targets_only' : 'all')} />
        </div>

        <div className={ROW}>
          <span className="text-sm text-slate-800">{t('quiet.label')}</span>
          <Switch checked={!!qh.enabled} label={t('quiet.label')} tid="alert-prefs-quiet"
            onChange={(v) => save('quiet_hours', { ...qh, enabled: v })} />
        </div>
        {qh.enabled && (
          <div className={ROW}>
            <label className="flex items-center gap-2 text-sm text-slate-800">
              {t('quiet.start')}
              <input type="time" className={INPUT} data-tid="alert-prefs-quiet-start" value={qh.start}
                onChange={(e) => setTime('start', e.target.value)} />
            </label>
            <label className="flex items-center gap-2 text-sm text-slate-800">
              {t('quiet.end')}
              <input type="time" className={INPUT} data-tid="alert-prefs-quiet-end" value={qh.end}
                onChange={(e) => setTime('end', e.target.value)} />
            </label>
          </div>
        )}
        {quietInactive && (
          <div className="py-2 text-sm text-amber-800" data-tid="alert-prefs-quiet-inactive">
            <p>{t('quiet.inactive')}</p>
            {!prefs.timezone && zone && (
              <button type="button" className={`${BTN} mt-2 text-sm`} data-tid="alert-prefs-use-timezone"
                disabled={busyZone} onClick={useBrowserZone}>
                {t('quiet.use_timezone', { tz: zone })}
              </button>
            )}
          </div>
        )}
        {qh.enabled && prefs.timezone && (
          <p className="py-1 text-xs text-slate-500" data-tid="alert-prefs-timezone">{t('quiet.timezone', { tz: prefs.timezone })}</p>
        )}

        <div className="py-2">
          <p className="text-sm font-medium text-slate-800">{t('caps.label')}</p>
          <p className="text-xs text-slate-500">{t('caps.hint')}</p>
          {KINDS.map((k) => (
            <div key={k} className={ROW}>
              <span id={`alert-prefs-cap-${k}`} className="text-sm text-slate-800">{t(`kind.${k}`)}</span>
              <span className="flex items-center gap-1" role="group" aria-labelledby={`alert-prefs-cap-${k}`}>
                <button type="button" className={BTN} data-tid={`alert-prefs-cap-${k}-dec`} aria-label={t('caps.less', { kind: t(`kind.${k}`) })}
                  disabled={(caps[k] ?? 3) <= 1} onClick={() => stepCap(k, -1)}>−</button>
                <output className="min-w-[2rem] text-center text-sm tabular-nums text-slate-900" data-tid={`alert-prefs-cap-${k}-value`}>{caps[k] ?? 3}</output>
                <button type="button" className={BTN} data-tid={`alert-prefs-cap-${k}-inc`} aria-label={t('caps.more', { kind: t(`kind.${k}`) })}
                  disabled={(caps[k] ?? 3) >= 10} onClick={() => stepCap(k, 1)}>+</button>
              </span>
            </div>
          ))}
        </div>

        <div className={ROW}>
          <label htmlFor="alert-prefs-group" className="max-w-[60%] text-sm text-slate-800">
            {t('group.label')}
            <span className="block text-xs text-slate-500">{t('group.hint')}</span>
          </label>
          <select id="alert-prefs-group" className={INPUT} data-tid="alert-prefs-group" value={groupValue}
            onChange={(e) => save('group_window_min', Number(e.target.value))}>
            {groupOptions.map((m) => <option key={m} value={m}>{m === 0 ? t('group.off') : t('group.minutes', { count: m })}</option>)}
          </select>
        </div>
      </div>
    </section>
  )
}
