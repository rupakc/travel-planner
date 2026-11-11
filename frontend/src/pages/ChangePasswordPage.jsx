import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Lock } from 'lucide-react'
import { useTranslation, Trans } from 'react-i18next'
import { useAuth } from '../context/AuthContext'
import AttributionFooter from '../components/ui/AttributionFooter'
import { MIN_PASSWORD_LENGTH } from '../utils/passwordStrength'
import { responseErrorMessage } from '../utils/httpError'

export default function ChangePasswordPage() {
  const { t } = useTranslation('account')
  const { token, updateTokenAfterPasswordChange, user } = useAuth()
  const navigate = useNavigate()
  const [form, setForm] = useState({ current: '', next: '', confirm: '' })
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  const handleSubmit = async (e) => {
    e.preventDefault()
    setError('')
    if (form.next !== form.confirm) { setError(t('changePassword.mismatch')); return }
    if (form.next.length < MIN_PASSWORD_LENGTH) { setError(t('changePassword.tooShort')); return }
    setLoading(true)
    try {
      const res = await fetch('/api/auth/change-password', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify({ current_password: form.current, new_password: form.next }),
      })
      if (!res.ok) {
        // error_code first (password_too_short, password_common, …), then detail.
        setError(await responseErrorMessage(res, t('changePassword.failed')))
        return
      }
      const data = await res.json()
      updateTokenAfterPasswordChange(data.access_token)
      navigate('/', { replace: true })
    } catch {
      setError(t('changePassword.generic'))
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen flex flex-col items-center justify-center bg-gradient-to-br from-teal-50 via-slate-50 to-sky-50 px-4">
      <div className="bg-white rounded-3xl shadow-lg ring-1 ring-gray-100 w-full max-w-md p-8">
        <div className="mb-6 text-center">
          <div className="w-14 h-14 mx-auto rounded-2xl bg-gradient-to-br from-teal-500 to-teal-700 flex items-center justify-center mb-4 shadow-lg">
            <Lock size={26} className="text-white" />
          </div>
          <h1 className="font-display text-2xl font-bold text-gray-800">{t('changePassword.title')}</h1>
          <p className="text-sm text-gray-500 mt-1">
            <Trans i18nKey="changePassword.welcome" ns="account" values={{ username: user?.username }} components={{ strong: <strong /> }} />
          </p>
        </div>

        {error && (
          <div className="mb-4 p-3 rounded-lg bg-red-50 text-red-700 text-sm border border-red-200">
            {error}
          </div>
        )}

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">{t('changePassword.temporary')}</label>
            <input
              type="password"
              value={form.current}
              data-tid="change-password.temporary"
              onChange={e => setForm(f => ({ ...f, current: e.target.value }))}
              className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-teal-500"
              required
              autoFocus
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">{t('changePassword.new')}</label>
            <input
              type="password"
              value={form.next}
              data-tid="change-password.new"
              onChange={e => setForm(f => ({ ...f, next: e.target.value }))}
              className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-teal-500"
              placeholder={t('changePassword.newPlaceholder')}
              minLength={MIN_PASSWORD_LENGTH}
              required
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">{t('changePassword.confirm')}</label>
            <input
              type="password"
              value={form.confirm}
              data-tid="change-password.confirm"
              onChange={e => setForm(f => ({ ...f, confirm: e.target.value }))}
              className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-teal-500"
              required
            />
          </div>
          <button
            type="submit"
            data-tid="change-password.submit"
            disabled={loading}
            className="w-full py-2.5 bg-teal-600 hover:bg-teal-700 disabled:bg-teal-300 text-white font-semibold rounded-lg transition-colors"
          >
            {loading ? t('changePassword.saving') : t('changePassword.submit')}
          </button>
        </form>
      </div>
      <AttributionFooter />
    </div>
  )
}
