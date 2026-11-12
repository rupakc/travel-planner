import { useState, useEffect, useCallback } from 'react'
import { useTranslation, Trans } from 'react-i18next'
import { useAuth } from '../context/AuthContext'
import { fmtDate } from '../i18n/format'
import { getTelemetrySummary } from '../services/api'
import TelemetrySummary from '../components/admin/TelemetrySummary'
import InvitesPanel from '../components/admin/InvitesPanel'
import { listInvites } from '../services/adminInvitesApi'
import { MIN_PASSWORD_LENGTH } from '../utils/passwordStrength'
import { responseErrorMessage } from '../utils/httpError'

const TABS = ['Users', 'Feedback', 'Analytics', 'Invites']

export default function AdminPage() {
  const { t } = useTranslation('account')
  const { token, user } = useAuth()
  const { t: tt } = useTranslation('adminTelemetry')
  const { t: ti } = useTranslation('adminInvites')
  const [tab, setTab] = useState('Users')
  // Probed once on mount: a 404 means an older backend, so the tab is hidden.
  const [analytics, setAnalytics] = useState({ summary: null, error: null, hidden: true })

  useEffect(() => {
    let live = true
    getTelemetrySummary(30, token)
      .then(summary => live && setAnalytics({ summary, error: null, hidden: false }))
      .catch(error => {
        if (!live) return
        const hidden = error?.response?.status === 404
        setAnalytics({ summary: null, error: hidden ? null : error, hidden })
        if (hidden) setTab(cur => (cur === 'Analytics' ? 'Users' : cur))
      })
    return () => { live = false }
  }, [token])

  // Same probe for invites: hidden until the backend has the endpoint.
  const [invites, setInvites] = useState({ rows: null, hidden: true })
  useEffect(() => {
    let live = true
    listInvites(token)
      .then(rows => live && setInvites({ rows, hidden: false }))
      .catch(error => {
        if (!live) return
        // Only a 404 is "older backend"; other failures keep the tab so the panel can show the error.
        const hidden = error?.status === 404
        setInvites({ rows: null, hidden })
        if (hidden) setTab(cur => (cur === 'Invites' ? 'Users' : cur))
      })
    return () => { live = false }
  }, [token])

  return (
    <div className="max-w-5xl mx-auto px-4 py-8">
      <h1 className="font-display text-2xl font-bold text-gray-800 mb-6">{t('admin.title')}</h1>

      <div className="flex gap-2 mb-6 border-b border-gray-200">
        {TABS.filter(id => (id !== 'Analytics' || !analytics.hidden) && (id !== 'Invites' || !invites.hidden)).map(id => (
          <button
            key={id}
            data-tid={`admin.tab-${id}`}
            onClick={() => setTab(id)}
            className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
              tab === id
                ? 'border-teal-600 text-teal-700'
                : 'border-transparent text-gray-500 hover:text-gray-700'
            }`}
          >
            {id === 'Analytics' ? tt('tab') : id === 'Invites' ? ti('tab') : t(`admin.tabs.${id.toLowerCase()}`)}
          </button>
        ))}
      </div>

      {tab === 'Users'    && <UsersTab token={token} currentUsername={user?.username} />}
      {tab === 'Feedback' && <FeedbackTab token={token} />}
      {tab === 'Invites'   && <InvitesPanel token={token} initial={invites.rows} />}
      {tab === 'Analytics' && <TelemetrySummary summary={analytics.summary} error={analytics.error} />}
    </div>
  )
}

// ── Users Tab ─────────────────────────────────────────────────────────────────

function UsersTab({ token, currentUsername }) {
  const { t } = useTranslation('account')
  const [users, setUsers] = useState([])
  const [loading, setLoading] = useState(true)
  const [showCreate, setShowCreate] = useState(false)
  const [form, setForm] = useState({ username: '', email: '', password: '', is_admin: false })
  const [formError, setFormError] = useState('')
  const [formLoading, setFormLoading] = useState(false)
  const [resetTarget, setResetTarget] = useState(null) // username string or null

  const fetchUsers = () => {
    setLoading(true)
    fetch('/api/admin/users', { headers: { Authorization: `Bearer ${token}` } })
      .then(r => r.json())
      .then(setUsers)
      .finally(() => setLoading(false))
  }

  useEffect(fetchUsers, [])

  const createUser = async (e) => {
    e.preventDefault()
    setFormError('')
    setFormLoading(true)
    try {
      const res = await fetch('/api/admin/users', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify(form),
      })
      if (!res.ok) {
        setFormError(await responseErrorMessage(res, t('admin.users.createFailed')))
        return
      }
      setForm({ username: '', email: '', password: '', is_admin: false })
      setShowCreate(false)
      fetchUsers()
    } catch {
      setFormError(t('admin.common.wentWrong'))
    } finally {
      setFormLoading(false)
    }
  }

  const toggleActive = async (user) => {
    const url = user.is_active
      ? `/api/admin/users/${user.username}`
      : `/api/admin/users/${user.username}/reactivate`
    const method = user.is_active ? 'DELETE' : 'POST'
    await fetch(url, { method, headers: { Authorization: `Bearer ${token}` } })
    fetchUsers()
  }

  return (
    <div>
      <div className="flex justify-between items-center mb-4">
        <p className="text-sm text-gray-500">{t('admin.users.count', { count: users.length })}</p>
        <button
          onClick={() => setShowCreate(s => !s)}
          data-tid="admin.create-user"
          className="px-4 py-2 bg-teal-700 hover:bg-teal-800 text-white text-sm font-medium rounded-lg transition-colors"
        >
          {t('admin.users.create')}
        </button>
      </div>

      {showCreate && (
        <form onSubmit={createUser} className="mb-6 p-4 bg-teal-50 border border-teal-200 rounded-xl space-y-3">
          <h3 className="font-semibold text-teal-800 text-sm">{t('admin.users.newUser')}</h3>
          {formError && <p className="text-red-600 text-sm">{formError}</p>}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">{t('admin.users.usernameRequired')}</label>
              <input data-tid="admin.new-username" value={form.username} onChange={e => setForm(f => ({ ...f, username: e.target.value }))}
                className="w-full px-3 py-1.5 border border-gray-300 rounded-lg text-sm" required />
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">{t('admin.users.emailOptional')}</label>
              <input data-tid="admin.new-email" type="email" value={form.email} onChange={e => setForm(f => ({ ...f, email: e.target.value }))}
                className="w-full px-3 py-1.5 border border-gray-300 rounded-lg text-sm" />
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">{t('admin.users.tempPasswordRequired')}</label>
              <input data-tid="admin.new-password" type="password" value={form.password} onChange={e => setForm(f => ({ ...f, password: e.target.value }))}
                placeholder={t('admin.reset.minPlaceholder')} minLength={MIN_PASSWORD_LENGTH}
                className="w-full px-3 py-1.5 border border-gray-300 rounded-lg text-sm" required />
            </div>
            <div className="flex items-end pb-1">
              <label className="flex items-center gap-2 text-sm text-gray-700">
                <input data-tid="admin.new-is-admin" type="checkbox" checked={form.is_admin} onChange={e => setForm(f => ({ ...f, is_admin: e.target.checked }))}
                  className="w-4 h-4 accent-teal-600" />
                {t('admin.users.adminPrivileges')}
              </label>
            </div>
          </div>
          <div className="flex gap-2">
            <button type="submit" disabled={formLoading} data-tid="admin.create-submit"
              className="px-4 py-1.5 bg-teal-700 hover:bg-teal-800 disabled:bg-teal-300 text-white text-sm font-medium rounded-lg">
              {formLoading ? t('admin.users.creating') : t('admin.users.createSubmit')}
            </button>
            <button type="button" onClick={() => setShowCreate(false)} data-tid="admin.create-cancel"
              className="px-4 py-1.5 bg-gray-100 hover:bg-gray-200 text-gray-700 text-sm font-medium rounded-lg">
              {t('admin.common.cancel')}
            </button>
          </div>
        </form>
      )}

      {loading ? (
        <p className="text-sm text-gray-400">{t('admin.common.loading')}</p>
      ) : (
        <div className="overflow-x-auto rounded-xl border border-gray-200">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 text-gray-600 text-xs uppercase">
              <tr>
                <th className="px-4 py-3 text-left">{t('admin.table.username')}</th>
                <th className="px-4 py-3 text-left hidden sm:table-cell">{t('admin.table.email')}</th>
                <th className="px-4 py-3 text-left hidden md:table-cell">{t('admin.table.created')}</th>
                <th className="px-4 py-3 text-center">{t('admin.table.role')}</th>
                <th className="px-4 py-3 text-center">{t('admin.table.status')}</th>
                <th className="px-4 py-3 text-center">{t('admin.table.actions')}</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {users.map(u => (
                <tr key={u.username} className={u.is_active ? '' : 'opacity-50 bg-gray-50'}>
                  <td className="px-4 py-3 font-medium">{u.username}</td>
                  <td className="px-4 py-3 text-gray-500 hidden sm:table-cell">{u.email || '—'}</td>
                  <td className="px-4 py-3 text-gray-500 hidden md:table-cell">
                    {u.created_at ? fmtDate(u.created_at) : '—'}
                  </td>
                  <td className="px-4 py-3 text-center">
                    <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${u.is_admin ? 'bg-purple-100 text-purple-700' : 'bg-gray-100 text-gray-600'}`}>
                      {u.is_admin ? t('admin.role.admin') : t('admin.role.user')}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-center">
                    <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${u.is_active ? 'bg-green-100 text-green-700' : 'bg-red-100 text-red-600'}`}>
                      {u.is_active ? (u.is_first_login ? t('admin.status.pending') : t('admin.status.active')) : t('admin.status.inactive')}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-center">
                    <div className="flex items-center justify-center gap-1">
                      {u.is_active && (
                        <button
                          onClick={() => setResetTarget(u.username)}
                          data-tid="admin.reset-password"
                          title={u.username === currentUsername ? t('admin.users.resetOwnHint') : undefined}
                          className={`text-xs px-2 py-1 rounded-md font-medium transition-colors ${
                            u.username === currentUsername
                              ? 'text-amber-600 hover:bg-amber-50'
                              : 'text-teal-600 hover:bg-teal-50'
                          }`}>
                          {u.username === currentUsername ? t('admin.users.resetOwn') : t('admin.users.reset')}
                        </button>
                      )}
                      <button onClick={() => toggleActive(u)} data-tid="admin.toggle-active"
                        className={`text-xs px-2 py-1 rounded-md font-medium transition-colors ${
                          u.is_active
                            ? 'text-red-600 hover:bg-red-50'
                            : 'text-green-600 hover:bg-green-50'
                        }`}>
                        {u.is_active ? t('admin.users.deactivate') : t('admin.users.reactivate')}
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {resetTarget && (
        <ResetPasswordModal
          username={resetTarget}
          token={token}
          isSelf={resetTarget === currentUsername}
          onClose={() => setResetTarget(null)}
        />
      )}
    </div>
  )
}

// ── Reset Password Modal ──────────────────────────────────────────────────────

function ResetPasswordModal({ username, token, isSelf, onClose }) {
  const { t } = useTranslation('account')
  const [form, setForm] = useState({ password: '', confirm: '' })
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const [success, setSuccess] = useState(false)

  const handleClose = useCallback(() => {
    if (!loading) onClose()
  }, [loading, onClose])

  useEffect(() => {
    const onKeyDown = (e) => { if (e.key === 'Escape') handleClose() }
    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
  }, [handleClose])

  const handleSubmit = async (e) => {
    e.preventDefault()
    setError('')
    if (form.password.length < MIN_PASSWORD_LENGTH) {
      setError(t('admin.reset.tooShort'))
      return
    }
    if (form.password !== form.confirm) {
      setError(t('admin.reset.mismatch'))
      return
    }
    setLoading(true)
    try {
      const res = await fetch(
        `/api/admin/users/${encodeURIComponent(username)}/reset-password`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
          body: JSON.stringify({ new_password: form.password }),
        }
      )
      if (!res.ok) {
        setError(await responseErrorMessage(res, t('admin.reset.failed')))
        return
      }
      setSuccess(true)
    } catch {
      setError(t('admin.common.wentWrong'))
    } finally {
      setLoading(false)
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40"
      onClick={handleClose}
    >
      <div
        className="bg-white rounded-2xl shadow-xl w-full max-w-md mx-4 p-6"
        onClick={e => e.stopPropagation()}
      >
        <h2 className="text-lg font-semibold text-gray-800 mb-1">{t('admin.reset.title')}</h2>
        <p className="text-sm text-gray-500 mb-3">
          <Trans i18nKey="admin.reset.intro" ns="account" values={{ username }}
            components={{ name: <span className="font-medium text-gray-700" /> }} />
        </p>
        {isSelf && (
          <p className="text-sm text-amber-700 bg-amber-50 border border-amber-200 rounded-lg px-3 py-2 mb-3">
            {t('admin.reset.selfWarning')}
          </p>
        )}

        {success ? (
          <div className="space-y-4">
            <p className="text-sm text-green-700 bg-green-50 border border-green-200 rounded-lg px-4 py-3">
              {t('admin.reset.success', { username })}
            </p>
            <button onClick={onClose} data-tid="admin.reset-close"
              className="w-full px-4 py-2 bg-gray-100 hover:bg-gray-200 text-gray-700 text-sm font-medium rounded-lg transition-colors">
              {t('admin.common.close')}
            </button>
          </div>
        ) : (
          <form onSubmit={handleSubmit} className="space-y-3">
            {error && (
              <p className="text-sm text-red-600 bg-red-50 border border-red-200 rounded-lg px-3 py-2">
                {error}
              </p>
            )}
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">{t('admin.reset.newPassword')}</label>
              <input
                type="password" data-tid="admin.reset-new-password"
                value={form.password}
                onChange={e => setForm(f => ({ ...f, password: e.target.value }))}
                className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-teal-400"
                placeholder={t('admin.reset.minPlaceholder')}
                required
                autoFocus
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">{t('admin.reset.confirmPassword')}</label>
              <input
                type="password" data-tid="admin.reset-confirm-password"
                value={form.confirm}
                onChange={e => setForm(f => ({ ...f, confirm: e.target.value }))}
                className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-teal-400"
                placeholder={t('admin.reset.repeatPlaceholder')}
                required
              />
            </div>
            <div className="flex gap-2 pt-1">
              <button type="submit" disabled={loading} data-tid="admin.reset-submit"
                className="flex-1 px-4 py-2 bg-teal-700 hover:bg-teal-800 disabled:bg-teal-300 text-white text-sm font-medium rounded-lg transition-colors">
                {loading ? t('admin.reset.submitting') : t('admin.reset.submit')}
              </button>
              <button type="button" onClick={handleClose} disabled={loading} data-tid="admin.reset-cancel"
                className="flex-1 px-4 py-2 bg-gray-100 hover:bg-gray-200 disabled:opacity-50 text-gray-700 text-sm font-medium rounded-lg transition-colors">
                {t('admin.common.cancel')}
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  )
}

// ── Feedback Tab ──────────────────────────────────────────────────────────────

function FeedbackTab({ token }) {
  const { t } = useTranslation('account')
  const [items, setItems] = useState([])
  const [loading, setLoading] = useState(true)
  const [filter, setFilter] = useState({ page: '', category: '', minRating: '' })

  useEffect(() => {
    setLoading(true)
    const params = new URLSearchParams()
    if (filter.page)      params.set('page', filter.page)
    if (filter.category)  params.set('category', filter.category)
    if (filter.minRating) params.set('min_rating', filter.minRating)
    fetch(`/api/admin/feedback?${params}`, { headers: { Authorization: `Bearer ${token}` } })
      .then(r => r.json())
      .then(setItems)
      .finally(() => setLoading(false))
  }, [filter])

  const exportCSV = () => {
    const rows = [
      ['Date', 'Page', 'Rating', 'Category', 'Message', 'Username'],
      ...items.map(i => [
        i.created_at, i.page, i.rating, i.category,
        `"${(i.message || '').replace(/"/g, '""')}"`,
        i.username || '',
      ]),
    ]
    const csv = rows.map(r => r.join(',')).join('\n')
    const a = document.createElement('a')
    a.href = URL.createObjectURL(new Blob([csv], { type: 'text/csv' }))
    a.download = 'feedback.csv'
    a.click()
  }

  const STARS = [1, 2, 3, 4, 5]
  const CATEGORIES = ['bug', 'feature_request', 'general', 'praise']
  const PAGES = ['search', 'results', 'chat', 'preferences', 'admin']

  return (
    <div>
      <div className="flex flex-wrap gap-3 mb-4 items-end">
        <div>
          <label className="block text-xs text-gray-500 mb-1">{t('admin.feedback.page')}</label>
          <select data-tid="admin.feedback-page" value={filter.page} onChange={e => setFilter(f => ({ ...f, page: e.target.value }))}
            className="px-2 py-1.5 text-sm border border-gray-300 rounded-lg">
            <option value="">{t('admin.feedback.all')}</option>
            {PAGES.map(p => <option key={p} value={p}>{t(`admin.feedback.pages.${p}`, { defaultValue: p })}</option>)}
          </select>
        </div>
        <div>
          <label className="block text-xs text-gray-500 mb-1">{t('admin.feedback.category')}</label>
          <select data-tid="admin.feedback-category" value={filter.category} onChange={e => setFilter(f => ({ ...f, category: e.target.value }))}
            className="px-2 py-1.5 text-sm border border-gray-300 rounded-lg">
            <option value="">{t('admin.feedback.all')}</option>
            {CATEGORIES.map(c => <option key={c} value={c}>{t(`admin.feedback.categories.${c}`, { defaultValue: c.replace('_', ' ') })}</option>)}
          </select>
        </div>
        <div>
          <label className="block text-xs text-gray-500 mb-1">{t('admin.feedback.minRating')}</label>
          <select data-tid="admin.feedback-min-rating" value={filter.minRating} onChange={e => setFilter(f => ({ ...f, minRating: e.target.value }))}
            className="px-2 py-1.5 text-sm border border-gray-300 rounded-lg">
            <option value="">{t('admin.feedback.any')}</option>
            {STARS.map(s => <option key={s} value={s}>{s}★+</option>)}
          </select>
        </div>
        <button onClick={exportCSV} data-tid="admin.export-csv"
          className="ml-auto px-3 py-1.5 text-sm bg-gray-100 hover:bg-gray-200 text-gray-700 font-medium rounded-lg transition-colors">
          {t('admin.feedback.export')}
        </button>
      </div>

      {loading ? (
        <p className="text-sm text-gray-400">{t('admin.common.loading')}</p>
      ) : items.length === 0 ? (
        <p className="text-sm text-gray-400 py-8 text-center">{t('admin.feedback.empty')}</p>
      ) : (
        <div className="space-y-3">
          {items.map(item => (
            <div key={item.id} className="p-4 bg-white border border-gray-200 rounded-xl">
              <div className="flex flex-wrap gap-2 items-center mb-2">
                <span className="text-yellow-400 text-sm">{'★'.repeat(item.rating)}{'☆'.repeat(5 - item.rating)}</span>
                <span className="px-2 py-0.5 bg-blue-100 text-blue-700 text-xs rounded-full capitalize">
                  {t(`admin.feedback.pages.${item.page}`, { defaultValue: item.page })}
                </span>
                <span className="px-2 py-0.5 bg-gray-100 text-gray-600 text-xs rounded-full capitalize">
                  {t(`admin.feedback.categories.${item.category}`, { defaultValue: (item.category || '').replace('_', ' ') })}
                </span>
                <span className="text-xs text-gray-400 ml-auto">
                  {item.created_at ? fmtDate(item.created_at, { year: 'numeric', month: 'numeric', day: 'numeric', hour: 'numeric', minute: 'numeric', second: 'numeric' }) : ''}
                  {item.username ? ` · ${item.username}` : ''}
                </span>
              </div>
              {item.message && <p className="text-sm text-gray-700">{item.message}</p>}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
