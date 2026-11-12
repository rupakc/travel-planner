import { useState, useEffect, useCallback } from 'react'
import { useTranslation } from 'react-i18next'
import { fmtDate } from '../../i18n/format'
import { errorText } from '../../services/apiError'
import { listQueue, decide, restrictUser, liftRestriction } from '../../services/adminSocialApi'
import { emit } from '../../telemetry/client'

const STATUSES = ['held', 'reported', 'hidden']
const btn = 'min-h-[44px] px-3 rounded-lg text-sm font-medium border disabled:opacity-50'

/** Moderation queue. All user text is rendered as plain text. */
export default function ModerationQueue({ token }) {
  const { t } = useTranslation(['adminSocial', 'errors'])
  const [status, setStatus] = useState('held')
  const [items, setItems] = useState([])
  const [next, setNext] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [days, setDays] = useState(7)
  const [busy, setBusy] = useState(false)

  const load = useCallback((st, cursor) => (
    listQueue(token, st, cursor)
      .then((res) => {
        setItems((cur) => (cursor ? [...cur, ...res.items] : res.items))
        setNext(res.next || null)
      })
      .catch((e) => setError(errorText(t, e)))
      .finally(() => setLoading(false))
  ), [token, t])

  useEffect(() => {
    setLoading(true)
    setError('')
    setItems([])
    setNext(null)
    emit('admin_mod_action', { action: 'view_queue' })
    load(status)
  }, [status, load])

  const act = async (fn, action, after) => {
    setError('')
    setNotice('')
    setBusy(true)
    try {
      await fn()
      emit('admin_mod_action', { action })
      after?.()
    } catch (e) {
      setError(errorText(t, e))
    } finally {
      setBusy(false)
    }
  }

  const onDecide = (it, action) =>
    act(() => decide(token, it.target, it.id, action), action, () =>
      setItems((cur) => cur.filter((x) => !(x.target === it.target && x.id === it.id))))

  const onRestrict = (it) =>
    act(() => restrictUser(token, it.author_handle, Number(days)), 'restrict', () =>
      setNotice(t('restricted', { days: Number(days) })))

  const onLift = (it) =>
    act(() => liftRestriction(token, it.author_handle), 'lift', () => setNotice(t('lifted')))

  return (
    <div data-tid="adminSocial.root">
      <div className="flex flex-wrap gap-2 mb-4" role="tablist">
        {STATUSES.map((s) => (
          <button
            key={s}
            role="tab"
            aria-selected={status === s}
            data-tid={`adminSocial.status-${s}`}
            onClick={() => setStatus(s)}
            className={`${btn} ${status === s ? 'bg-teal-700 text-white border-teal-700' : 'bg-white text-gray-700 border-gray-300'}`}
          >
            {t(`status.${s}`)}
          </button>
        ))}
      </div>

      <label className="flex items-center gap-2 text-sm text-gray-600 mb-4">
        {t('restrictDays')}
        <input
          type="number" min="1" max="365" value={days}
          data-tid="adminSocial.days"
          onChange={(e) => setDays(Math.min(365, Math.max(1, Number(e.target.value) || 1)))}
          className="w-24 min-h-[44px] px-3 border border-gray-300 rounded-lg text-sm bg-white text-gray-800"
        />
      </label>

      {error && <p role="alert" className="text-sm text-red-600 mb-3">{error}</p>}
      {notice && <p role="status" className="text-sm text-green-700 mb-3">{notice}</p>}
      {loading && <p className="text-sm text-gray-500">{t('loading')}</p>}
      {!loading && !items.length && !error && <p className="text-sm text-gray-500">{t('empty')}</p>}

      <ul className="space-y-3">
        {items.map((it) => (
          <li key={`${it.target}:${it.id}`} data-tid="adminSocial.item" className="bg-white border border-gray-200 rounded-xl p-4">
            <div className="flex flex-wrap items-center gap-2 text-xs text-gray-500 mb-2">
              <span className="px-2 py-0.5 rounded-full bg-gray-100 text-gray-700">{t(`target.${it.target}`, { defaultValue: it.target })}</span>
              {it.author_handle && <span>{t('by', { handle: it.author_handle })}</span>}
              {it.created_at && <span>{fmtDate(it.created_at)}</span>}
            </div>
            <p className="text-sm text-gray-800 whitespace-pre-wrap break-words">{it.excerpt}</p>
            {it.reason_counts && Object.keys(it.reason_counts).length > 0 && (
              <p className="text-xs text-gray-500 mt-2">
                {Object.entries(it.reason_counts).map(([k, n]) => `${t(`reason.${k}`, { defaultValue: k })}: ${n}`).join(' · ')}
              </p>
            )}
            <div className="flex flex-wrap gap-2 mt-3">
              <button type="button" disabled={busy} data-tid="adminSocial.approve" onClick={() => onDecide(it, 'approve')}
                className={`${btn} border-green-600 text-green-700 bg-white`}>{t('approve')}</button>
              <button type="button" disabled={busy} data-tid="adminSocial.remove" onClick={() => onDecide(it, 'remove')}
                className={`${btn} border-red-600 text-red-600 bg-white`}>{t('remove')}</button>
              {it.author_handle && (
                <>
                  <button type="button" disabled={busy} data-tid="adminSocial.restrict" onClick={() => onRestrict(it)}
                    className={`${btn} border-gray-300 text-gray-700 bg-white`}>{t('restrict')}</button>
                  <button type="button" disabled={busy} data-tid="adminSocial.lift" onClick={() => onLift(it)}
                    className={`${btn} border-gray-300 text-gray-700 bg-white`}>{t('lift')}</button>
                </>
              )}
            </div>
          </li>
        ))}
      </ul>

      {next && (
        <button type="button" data-tid="adminSocial.more" onClick={() => load(status, next)}
          className={`${btn} mt-4 border-gray-300 text-gray-700 bg-white`}>{t('more')}</button>
      )}
    </div>
  )
}
