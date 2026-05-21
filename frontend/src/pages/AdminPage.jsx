import { useState, useEffect, useCallback } from 'react'
import { useAuth } from '../context/AuthContext'

const TABS = ['Users', 'Feedback']

export default function AdminPage() {
  const { token, user } = useAuth()
  const [tab, setTab] = useState('Users')

  return (
    <div className="max-w-5xl mx-auto px-4 py-8">
      <h1 className="font-display text-2xl font-bold text-gray-800 mb-6">Admin Panel</h1>

      <div className="flex gap-2 mb-6 border-b border-gray-200">
        {TABS.map(t => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
              tab === t
                ? 'border-teal-600 text-teal-700'
                : 'border-transparent text-gray-500 hover:text-gray-700'
            }`}
          >
            {t}
          </button>
        ))}
      </div>

      {tab === 'Users'    && <UsersTab token={token} currentUsername={user?.username} />}
      {tab === 'Feedback' && <FeedbackTab token={token} />}
    </div>
  )
}

// ── Users Tab ─────────────────────────────────────────────────────────────────

function UsersTab({ token, currentUsername }) {
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
        const err = await res.json()
        setFormError(err.detail || 'Failed to create user')
        return
      }
      setForm({ username: '', email: '', password: '', is_admin: false })
      setShowCreate(false)
      fetchUsers()
    } catch {
      setFormError('Something went wrong')
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
        <p className="text-sm text-gray-500">{users.length} user{users.length !== 1 ? 's' : ''}</p>
        <button
          onClick={() => setShowCreate(s => !s)}
          className="px-4 py-2 bg-teal-600 hover:bg-teal-700 text-white text-sm font-medium rounded-lg transition-colors"
        >
          + Create user
        </button>
      </div>

      {showCreate && (
        <form onSubmit={createUser} className="mb-6 p-4 bg-teal-50 border border-teal-200 rounded-xl space-y-3">
          <h3 className="font-semibold text-teal-800 text-sm">New user</h3>
          {formError && <p className="text-red-600 text-sm">{formError}</p>}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">Username *</label>
              <input value={form.username} onChange={e => setForm(f => ({ ...f, username: e.target.value }))}
                className="w-full px-3 py-1.5 border border-gray-300 rounded-lg text-sm" required />
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">Email (optional)</label>
              <input type="email" value={form.email} onChange={e => setForm(f => ({ ...f, email: e.target.value }))}
                className="w-full px-3 py-1.5 border border-gray-300 rounded-lg text-sm" />
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">Temporary password *</label>
              <input type="password" value={form.password} onChange={e => setForm(f => ({ ...f, password: e.target.value }))}
                className="w-full px-3 py-1.5 border border-gray-300 rounded-lg text-sm" required />
            </div>
            <div className="flex items-end pb-1">
              <label className="flex items-center gap-2 text-sm text-gray-700">
                <input type="checkbox" checked={form.is_admin} onChange={e => setForm(f => ({ ...f, is_admin: e.target.checked }))}
                  className="w-4 h-4 accent-teal-600" />
                Admin privileges
              </label>
            </div>
          </div>
          <div className="flex gap-2">
            <button type="submit" disabled={formLoading}
              className="px-4 py-1.5 bg-teal-600 hover:bg-teal-700 disabled:bg-teal-300 text-white text-sm font-medium rounded-lg">
              {formLoading ? 'Creating…' : 'Create'}
            </button>
            <button type="button" onClick={() => setShowCreate(false)}
              className="px-4 py-1.5 bg-gray-100 hover:bg-gray-200 text-gray-700 text-sm font-medium rounded-lg">
              Cancel
            </button>
          </div>
        </form>
      )}

      {loading ? (
        <p className="text-sm text-gray-400">Loading…</p>
      ) : (
        <div className="overflow-x-auto rounded-xl border border-gray-200">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 text-gray-600 text-xs uppercase">
              <tr>
                <th className="px-4 py-3 text-left">Username</th>
                <th className="px-4 py-3 text-left hidden sm:table-cell">Email</th>
                <th className="px-4 py-3 text-left hidden md:table-cell">Created</th>
                <th className="px-4 py-3 text-center">Role</th>
                <th className="px-4 py-3 text-center">Status</th>
                <th className="px-4 py-3 text-center">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {users.map(u => (
                <tr key={u.username} className={u.is_active ? '' : 'opacity-50 bg-gray-50'}>
                  <td className="px-4 py-3 font-medium">{u.username}</td>
                  <td className="px-4 py-3 text-gray-500 hidden sm:table-cell">{u.email || '—'}</td>
                  <td className="px-4 py-3 text-gray-500 hidden md:table-cell">
                    {u.created_at ? new Date(u.created_at).toLocaleDateString() : '—'}
                  </td>
                  <td className="px-4 py-3 text-center">
                    <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${u.is_admin ? 'bg-purple-100 text-purple-700' : 'bg-gray-100 text-gray-600'}`}>
                      {u.is_admin ? 'Admin' : 'User'}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-center">
                    <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${u.is_active ? 'bg-green-100 text-green-700' : 'bg-red-100 text-red-600'}`}>
                      {u.is_active ? (u.is_first_login ? 'Pending' : 'Active') : 'Inactive'}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-center">
                    <div className="flex items-center justify-center gap-1">
                      {u.is_active && (
                        <button
                          onClick={() => setResetTarget(u.username)}
                          title={u.username === currentUsername ? 'Resetting your own password will require you to set a new one on next page load' : undefined}
                          className={`text-xs px-2 py-1 rounded-md font-medium transition-colors ${
                            u.username === currentUsername
                              ? 'text-amber-600 hover:bg-amber-50'
                              : 'text-teal-600 hover:bg-teal-50'
                          }`}>
                          {u.username === currentUsername ? 'Reset own pw' : 'Reset pw'}
                        </button>
                      )}
                      <button onClick={() => toggleActive(u)}
                        className={`text-xs px-2 py-1 rounded-md font-medium transition-colors ${
                          u.is_active
                            ? 'text-red-600 hover:bg-red-50'
                            : 'text-green-600 hover:bg-green-50'
                        }`}>
                        {u.is_active ? 'Deactivate' : 'Reactivate'}
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
    if (form.password.length < 8) {
      setError('Password must be at least 8 characters')
      return
    }
    if (form.password !== form.confirm) {
      setError('Passwords do not match')
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
        const err = await res.json()
        setError(err.detail || 'Failed to reset password')
        return
      }
      setSuccess(true)
    } catch {
      setError('Something went wrong')
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
        <h2 className="text-lg font-semibold text-gray-800 mb-1">Reset password</h2>
        <p className="text-sm text-gray-500 mb-3">
          Setting a new password for <span className="font-medium text-gray-700">{username}</span>.
          They will be required to change it on next login.
        </p>
        {isSelf && (
          <p className="text-sm text-amber-700 bg-amber-50 border border-amber-200 rounded-lg px-3 py-2 mb-3">
            You are resetting your own password. You will be redirected to the change-password page on your next page load.
          </p>
        )}

        {success ? (
          <div className="space-y-4">
            <p className="text-sm text-green-700 bg-green-50 border border-green-200 rounded-lg px-4 py-3">
              Password reset for {username}. They will be prompted to set a new password on next login.
            </p>
            <button onClick={onClose}
              className="w-full px-4 py-2 bg-gray-100 hover:bg-gray-200 text-gray-700 text-sm font-medium rounded-lg transition-colors">
              Close
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
              <label className="block text-xs font-medium text-gray-600 mb-1">New password *</label>
              <input
                type="password"
                value={form.password}
                onChange={e => setForm(f => ({ ...f, password: e.target.value }))}
                className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-teal-400"
                placeholder="Min. 8 characters"
                required
                autoFocus
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">Confirm password *</label>
              <input
                type="password"
                value={form.confirm}
                onChange={e => setForm(f => ({ ...f, confirm: e.target.value }))}
                className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-teal-400"
                placeholder="Repeat the new password"
                required
              />
            </div>
            <div className="flex gap-2 pt-1">
              <button type="submit" disabled={loading}
                className="flex-1 px-4 py-2 bg-teal-600 hover:bg-teal-700 disabled:bg-teal-300 text-white text-sm font-medium rounded-lg transition-colors">
                {loading ? 'Resetting…' : 'Reset password'}
              </button>
              <button type="button" onClick={handleClose} disabled={loading}
                className="flex-1 px-4 py-2 bg-gray-100 hover:bg-gray-200 disabled:opacity-50 text-gray-700 text-sm font-medium rounded-lg transition-colors">
                Cancel
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
          <label className="block text-xs text-gray-500 mb-1">Page</label>
          <select value={filter.page} onChange={e => setFilter(f => ({ ...f, page: e.target.value }))}
            className="px-2 py-1.5 text-sm border border-gray-300 rounded-lg">
            <option value="">All</option>
            {PAGES.map(p => <option key={p} value={p}>{p}</option>)}
          </select>
        </div>
        <div>
          <label className="block text-xs text-gray-500 mb-1">Category</label>
          <select value={filter.category} onChange={e => setFilter(f => ({ ...f, category: e.target.value }))}
            className="px-2 py-1.5 text-sm border border-gray-300 rounded-lg">
            <option value="">All</option>
            {CATEGORIES.map(c => <option key={c} value={c}>{c.replace('_', ' ')}</option>)}
          </select>
        </div>
        <div>
          <label className="block text-xs text-gray-500 mb-1">Min rating</label>
          <select value={filter.minRating} onChange={e => setFilter(f => ({ ...f, minRating: e.target.value }))}
            className="px-2 py-1.5 text-sm border border-gray-300 rounded-lg">
            <option value="">Any</option>
            {STARS.map(s => <option key={s} value={s}>{s}★+</option>)}
          </select>
        </div>
        <button onClick={exportCSV}
          className="ml-auto px-3 py-1.5 text-sm bg-gray-100 hover:bg-gray-200 text-gray-700 font-medium rounded-lg transition-colors">
          Export CSV
        </button>
      </div>

      {loading ? (
        <p className="text-sm text-gray-400">Loading…</p>
      ) : items.length === 0 ? (
        <p className="text-sm text-gray-400 py-8 text-center">No feedback yet.</p>
      ) : (
        <div className="space-y-3">
          {items.map(item => (
            <div key={item.id} className="p-4 bg-white border border-gray-200 rounded-xl">
              <div className="flex flex-wrap gap-2 items-center mb-2">
                <span className="text-yellow-400 text-sm">{'★'.repeat(item.rating)}{'☆'.repeat(5 - item.rating)}</span>
                <span className="px-2 py-0.5 bg-blue-100 text-blue-700 text-xs rounded-full capitalize">
                  {item.page}
                </span>
                <span className="px-2 py-0.5 bg-gray-100 text-gray-600 text-xs rounded-full capitalize">
                  {(item.category || '').replace('_', ' ')}
                </span>
                <span className="text-xs text-gray-400 ml-auto">
                  {item.created_at ? new Date(item.created_at).toLocaleString() : ''}
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
