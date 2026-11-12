import { useState, useEffect, useCallback } from 'react'
import { useTranslation } from 'react-i18next'
import { fmtDate } from '../../i18n/format'
import { errorText } from '../../services/apiError'
import { listInvites, createInvite, revokeInvite } from '../../services/adminInvitesApi'

const inputCls = 'w-full px-3 py-1.5 border border-gray-300 rounded-lg text-sm bg-white text-gray-800'

function statusOf(inv, now) {
  if (inv.revoked_at) return 'revoked'
  if (inv.expires_at && new Date(inv.expires_at).getTime() <= now) return 'expired'
  if (inv.uses >= inv.max_uses) return 'used'
  return 'active'
}

const STATUS_CLS = {
  active: 'bg-green-100 text-green-700',
  revoked: 'bg-red-100 text-red-600',
  expired: 'bg-gray-100 text-gray-600',
  used: 'bg-gray-100 text-gray-600',
}

/** Invite codes. `initial` is the list the page fetched while probing; it seeds the first render only. */
export default function InvitesPanel({ token, initial = null }) {
  const { t } = useTranslation(['adminInvites', 'errors'])
  const [rows, setRows] = useState(initial || [])
  const [loading, setLoading] = useState(!initial)
  const [error, setError] = useState('')
  const [form, setForm] = useState({ max_uses: 1, expires_in_days: 14, note: '' })
  const [busy, setBusy] = useState(false)
  // The full code exists only in this state: the server never returns it again.
  const [created, setCreated] = useState(null)
  const [copied, setCopied] = useState(false)

  const reload = useCallback(() => (
    listInvites(token)
      .then(setRows)
      .catch((e) => setError(errorText(t, e)))
      .finally(() => setLoading(false))
  ), [token, t])

  // Always refetch on mount: `initial` only seeds the first render, so a remount never shows a stale list.
  useEffect(() => { reload() }, [reload])

  const submit = async (e) => {
    e.preventDefault()
    setError('')
    setBusy(true)
    try {
      const body = {
        max_uses: Number(form.max_uses),
        expires_in_days: Number(form.expires_in_days),
      }
      if (form.note.trim()) body.note = form.note.trim()
      setCreated(await createInvite(token, body))
      setCopied(false)
      setForm((f) => ({ ...f, note: '' }))
      await reload()
    } catch (err) {
      setError(errorText(t, err))
    } finally {
      setBusy(false)
    }
  }

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(created.code)
      setCopied(true)
    } catch { /* clipboard can be unavailable */ }
  }

  const revoke = async (id) => {
    setError('')
    try {
      await revokeInvite(token, id)
      await reload()
    } catch (err) {
      setError(errorText(t, err))
    }
  }

  const now = Date.now()

  return (
    <div data-tid="adminInvites.panel">
      <form onSubmit={submit} className="mb-6 p-4 bg-teal-50 border border-teal-200 rounded-xl space-y-3">
        <h3 className="font-semibold text-teal-800 text-sm">{t('adminInvites:newInvite')}</h3>
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
          <div>
            <label htmlFor="inv-max" className="block text-xs font-medium text-gray-600 mb-1">{t('adminInvites:maxUses')}</label>
            <input id="inv-max" data-tid="adminInvites.max-uses" type="number" min="1" max="1000" required
              value={form.max_uses} onChange={(e) => setForm((f) => ({ ...f, max_uses: e.target.value }))} className={inputCls} />
          </div>
          <div>
            <label htmlFor="inv-days" className="block text-xs font-medium text-gray-600 mb-1">{t('adminInvites:expiryDays')}</label>
            <input id="inv-days" data-tid="adminInvites.expiry-days" type="number" min="1" max="365" required
              value={form.expires_in_days} onChange={(e) => setForm((f) => ({ ...f, expires_in_days: e.target.value }))} className={inputCls} />
          </div>
          <div>
            <label htmlFor="inv-note" className="block text-xs font-medium text-gray-600 mb-1">{t('adminInvites:note')}</label>
            <input id="inv-note" data-tid="adminInvites.note" maxLength={80}
              value={form.note} onChange={(e) => setForm((f) => ({ ...f, note: e.target.value }))} className={inputCls} />
          </div>
        </div>
        <button type="submit" disabled={busy} data-tid="adminInvites.create"
          className="px-4 py-1.5 bg-teal-700 hover:bg-teal-800 disabled:bg-teal-300 text-white text-sm font-medium rounded-lg">
          {busy ? t('adminInvites:creating') : t('adminInvites:create')}
        </button>
      </form>

      {error && <p role="alert" className="mb-4 text-sm text-red-600">{error}</p>}

      {created && (
        <div role="status" data-tid="adminInvites.created" className="mb-6 p-4 border border-amber-300 bg-amber-50 rounded-xl">
          <p className="text-sm text-amber-800 mb-2">{t('adminInvites:shownOnce')}</p>
          <div className="flex flex-wrap items-center gap-2">
            <code data-tid="adminInvites.code" className="px-3 py-1.5 bg-white border border-amber-200 rounded-lg font-mono text-base text-gray-800">{created.code}</code>
            <button type="button" onClick={copy} data-tid="adminInvites.copy"
              className="px-3 py-1.5 text-sm bg-gray-100 hover:bg-gray-200 text-gray-700 font-medium rounded-lg">
              {copied ? t('adminInvites:copied') : t('adminInvites:copy')}
            </button>
            <button type="button" onClick={() => setCreated(null)} data-tid="adminInvites.dismiss"
              className="px-3 py-1.5 text-sm text-gray-600 hover:underline">
              {t('adminInvites:dismiss')}
            </button>
          </div>
        </div>
      )}

      {loading ? (
        <p className="text-sm text-gray-400">{t('adminInvites:loading')}</p>
      ) : rows.length === 0 ? (
        <p className="text-sm text-gray-400 py-8 text-center">{t('adminInvites:empty')}</p>
      ) : (
        <div className="overflow-x-auto rounded-xl border border-gray-200">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 text-gray-600 text-xs uppercase">
              <tr>
                <th className="px-4 py-3 text-left">{t('adminInvites:colCode')}</th>
                <th className="px-4 py-3 text-center">{t('adminInvites:colUses')}</th>
                <th className="px-4 py-3 text-left hidden sm:table-cell">{t('adminInvites:colExpires')}</th>
                <th className="px-4 py-3 text-left hidden md:table-cell">{t('adminInvites:colNote')}</th>
                <th className="px-4 py-3 text-center">{t('adminInvites:colStatus')}</th>
                <th className="px-4 py-3 text-center">{t('adminInvites:colActions')}</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {rows.map((inv) => {
                const status = statusOf(inv, now)
                return (
                  <tr key={inv.id} data-tid="adminInvites.row">
                    <td className="px-4 py-3 font-mono">{inv.code_prefix}…</td>
                    <td className="px-4 py-3 text-center">{t('adminInvites:usesOf', { used: inv.uses, max: inv.max_uses })}</td>
                    <td className="px-4 py-3 text-gray-500 hidden sm:table-cell">{inv.expires_at ? fmtDate(inv.expires_at) : '—'}</td>
                    <td className="px-4 py-3 text-gray-500 hidden md:table-cell">{inv.note || '—'}</td>
                    <td className="px-4 py-3 text-center">
                      <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${STATUS_CLS[status]}`}>{t(`adminInvites:status.${status}`)}</span>
                    </td>
                    <td className="px-4 py-3 text-center">
                      {status === 'active' && (
                        <button type="button" onClick={() => revoke(inv.id)} data-tid="adminInvites.revoke"
                          className="text-xs px-2 py-1 rounded-md font-medium text-red-600 hover:bg-red-50">
                          {t('adminInvites:revoke')}
                        </button>
                      )}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
