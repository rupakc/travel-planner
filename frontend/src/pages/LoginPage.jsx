import { useState } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import { Plane, Lock, User, Eye, EyeOff } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { useAuth } from '../context/AuthContext'
import { returnPathFrom } from '../utils/returnPath'
import SocialSignInButtons from '../components/auth/SocialSignInButtons'

export default function LoginPage() {
  const { t } = useTranslation('account')
  const { t: tAuth } = useTranslation('auth')
  const { login } = useAuth()
  const navigate   = useNavigate()
  const location   = useLocation()
  const from       = returnPathFrom(location)  // same-origin only

  const [form, setForm]     = useState({ username: '', password: '' })
  const [showPw, setShowPw] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError]   = useState('')

  const handleSubmit = async (e) => {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      await login(form.username, form.password)
      navigate(from, { replace: true })
    } catch (err) {
      setError(err.message || t('login.failed'))
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen bg-gradient-to-br from-teal-50 via-slate-50 to-sky-50 flex items-center justify-center px-4">
      <div className="w-full max-w-md">
        {/* Logo */}
        <div className="text-center mb-8">
          <div className="inline-flex items-center justify-center w-16 h-16 bg-gradient-to-br from-teal-500 to-teal-700 rounded-2xl shadow-lg mb-4">
            <Plane size={32} className="text-white" />
          </div>
          <h1 className="font-display text-3xl font-bold text-slate-800 tracking-tight">Travel Planner</h1>
          <p className="text-slate-500 mt-1">{t('login.tagline')}</p>
        </div>

        {/* Card */}
        <div className="bg-white rounded-3xl shadow-2xl ring-1 ring-gray-100 p-8">
          <h2 className="text-xl font-semibold text-gray-900 mb-6">{t('login.title')}</h2>

          {error && (
            <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-lg text-sm text-red-700">
              {error}
            </div>
          )}

          <SocialSignInButtons mode="signin" />

          <div className="flex items-center gap-3 my-5" role="separator">
            <span className="flex-1 h-px bg-gray-200 dark:bg-gray-700" />
            <span className="text-xs uppercase tracking-wide text-gray-400">{tAuth('divider')}</span>
            <span className="flex-1 h-px bg-gray-200 dark:bg-gray-700" />
          </div>

          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">{t('login.username')}</label>
              <div className="relative">
                <input
                  type="text" required autoFocus data-tid="login.username"
                  value={form.username}
                  onChange={e => setForm(f => ({ ...f, username: e.target.value }))}
                  placeholder={t('login.usernamePlaceholder')}
                  className="w-full pl-9 pr-3 py-2.5 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-teal-400 focus:border-teal-400 text-sm"
                />
                <User size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
              </div>
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">{t('login.password')}</label>
              <div className="relative">
                <input
                  type={showPw ? 'text' : 'password'} required data-tid="login.password"
                  value={form.password}
                  onChange={e => setForm(f => ({ ...f, password: e.target.value }))}
                  placeholder={t('login.passwordPlaceholder')}
                  className="w-full pl-9 pr-10 py-2.5 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-teal-400 focus:border-teal-400 text-sm"
                />
                <Lock size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
                <button type="button" onClick={() => setShowPw(v => !v)}
                  data-tid="login.toggle-password"
                  aria-label={showPw ? t('login.hidePassword') : t('login.showPassword')}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600">
                  {showPw ? <EyeOff size={14} /> : <Eye size={14} />}
                </button>
              </div>
            </div>

            <button type="submit" disabled={loading} data-tid="login.submit"
              className="w-full py-3 bg-gradient-to-r from-teal-600 to-teal-700 text-white font-semibold rounded-xl shadow-lg hover:from-teal-700 hover:to-teal-800 active:scale-[0.99] disabled:opacity-60 transition-all text-sm">
              {loading ? t('login.submitting') : t('login.submit')}
            </button>
          </form>

        </div>
      </div>
    </div>
  )
}
