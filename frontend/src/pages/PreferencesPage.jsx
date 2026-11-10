import { useState, useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { useAuth } from '../context/AuthContext'
import { useAlerts } from '../context/AlertsContext'
import { updateAccountEmail } from '../services/api'
import AlertEmailField from '../components/alerts/AlertEmailField'
import NationalitySearch from '../components/ui/NationalitySearch'
import TravelerPanel from '../components/ui/TravelerPanel'
import { track } from '../utils/analytics'
import TagInput from '../components/ui/TagInput'
import ThemeToggle from '../components/ui/ThemeToggle'
import LanguagePicker from '../components/ui/LanguagePicker'
import { PrivacySwitch } from '../components/ConsentPrompt'
import { useTheme } from '../theme/ThemeContext'
import { Save, Loader2, CheckCircle2, Globe, DollarSign, Users, Heart, MapPin, Sparkles, Trash2 } from 'lucide-react'

function TasteProfileCard({ token }) {
  const { t } = useTranslation('account')
  const [profile, setProfile] = useState(null)
  const [resetting, setResetting] = useState(false)

  const load = () => {
    fetch('/api/taste-profile', { headers: { Authorization: `Bearer ${token}` } })
      .then(r => (r.ok ? r.json() : Promise.reject()))
      .then(setProfile)
      .catch(() => setProfile(null))
  }
  useEffect(() => { if (token) load() }, [token])

  const handleReset = async () => {
    if (!window.confirm(t('prefs.taste.confirmReset'))) return
    setResetting(true)
    try {
      await fetch('/api/taste-profile', { method: 'DELETE', headers: { Authorization: `Bearer ${token}` } })
      track('taste_profile_reset', 'preferences')
      load()
    } finally { setResetting(false) }
  }

  const hasSignals = profile && profile.total_signals > 0

  return (
    <div className="px-6 md:px-8 py-6 space-y-4">
      <div className="flex items-center justify-between">
        <p className="text-[11px] font-semibold text-slate-400 uppercase tracking-widest">{t('prefs.taste.title')}</p>
        {hasSignals && (
          <button onClick={handleReset} disabled={resetting} data-tid="prefs.taste-reset"
            className="flex items-center gap-1 text-xs font-medium text-red-500 hover:text-red-700 disabled:opacity-50">
            <Trash2 size={12} /> {t('prefs.taste.reset')}
          </button>
        )}
      </div>
      <div className="flex items-start gap-3">
        <div className="w-9 h-9 rounded-xl bg-gradient-to-br from-amber-400 to-pink-500 flex items-center justify-center shrink-0">
          <Sparkles size={16} className="text-white" />
        </div>
        <div className="min-w-0">
          <p className="text-sm font-semibold text-gray-800">{t('prefs.taste.heading')}</p>
          {hasSignals ? (
            <p className="text-xs text-gray-500 mt-0.5">
              {t('prefs.taste.built', { count: profile.total_signals })}{' '}
              {t('prefs.taste.personalised')}
            </p>
          ) : (
            <p className="text-xs text-gray-500 mt-0.5">
              {t('prefs.taste.empty')}
            </p>
          )}
        </div>
      </div>
      {hasSignals && (
        <div className="space-y-2">
          {Object.entries(profile.signals).map(([type, entries]) => (
            <div key={type} className="flex flex-wrap items-center gap-1.5">
              <span className="text-xs font-medium text-gray-500 w-44 shrink-0">{t(`prefs.signal.${type}`, { defaultValue: type })}</span>
              {entries.slice(0, 4).map(e => (
                <span key={e.value} className="px-2 py-0.5 rounded-full bg-amber-50 border border-amber-200 text-amber-800 text-xs font-medium">
                  {e.value} <span className="text-amber-500">×{e.count}</span>
                </span>
              ))}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

const BUDGET_OPTIONS = [
  { value: 'low',    color: 'bg-green-100 text-green-700 border-green-300' },
  { value: 'medium', color: 'bg-teal-50 text-teal-700 border-teal-300' },
  { value: 'high',   color: 'bg-purple-100 text-purple-700 border-purple-300' },
]

const INTERESTS = [
  { id: 'food',      emoji: '🍜' },
  { id: 'history',   emoji: '🏛️' },
  { id: 'adventure', emoji: '🧗' },
  { id: 'culture',   emoji: '🎭' },
  { id: 'nature',    emoji: '🌿' },
  { id: 'shopping',  emoji: '🛍️' },
  { id: 'nightlife', emoji: '🌙' },
  { id: 'wellness',  emoji: '🧘' },
  { id: 'art',       emoji: '🎨' },
  { id: 'family',    emoji: '👨‍👩‍👧' },
]

export default function PreferencesPage() {
  const { t } = useTranslation('account')
  const { t: tp } = useTranslation('privacy')
  const { t: tc } = useTranslation('common')
  const { theme } = useTheme()
  const { token, refreshPreferences, user, setUserEmail } = useAuth()
  const { caps } = useAlerts()
  const [prefs, setPrefs] = useState(null)
  const [saving, setSaving] = useState(false)
  const [saveMsg, setSaveMsg] = useState('')
  const [saveIsError, setSaveIsError] = useState(false)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    if (!token) return
    fetch('/api/preferences', { headers: { Authorization: `Bearer ${token}` } })
      .then(r => r.ok ? r.json() : Promise.reject())
      .then(data => setPrefs(data))
      .catch(() => setPrefs({
        budget_category: 'medium', nationality: '', current_residence: '',
        residence_permits: [], existing_visas: [],
        interests: [], num_travelers: 1,
        adults: 1, children: 0, seniors: 0, infants: 0,
        accessibility_needs: [],
      }))
      .finally(() => setLoading(false))
  }, [token])

  const handleSave = async () => {
    setSaving(true); setSaveMsg(''); setSaveIsError(false)
    try {
      const totalTravelers = Math.max(1,
        (prefs.adults || 0) + (prefs.children || 0) + (prefs.seniors || 0) + (prefs.infants || 0))
      const res = await fetch('/api/preferences', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify({ ...prefs, num_travelers: totalTravelers }),
      })
      if (res.ok) {
        refreshPreferences()
        track('preferences_saved', 'preferences')
        setSaveMsg(t('prefs.saved'))
        setTimeout(() => setSaveMsg(''), 3000)
      } else {
        const err = await res.json()
        setSaveIsError(true)
        setSaveMsg(t('prefs.errorWithDetail', { detail: err.detail || t('prefs.saveFailed') }))
      }
    } catch { setSaveIsError(true); setSaveMsg(t('prefs.saveFailed')) }
    finally { setSaving(false) }
  }

  const toggleInterest = (id) =>
    setPrefs(p => ({ ...p, interests: p.interests.includes(id) ? p.interests.filter(i => i !== id) : [...p.interests, id] }))

  if (loading) return <div className="flex items-center justify-center h-[60vh] text-gray-400"><Loader2 className="animate-spin" size={24} /></div>
  if (!prefs) return null

  const labelClass = "block text-sm font-medium text-gray-700 mb-1.5"

  return (
    <div className="max-w-2xl mx-auto px-4 py-8">
      <div className="mb-6">
        <h1 className="font-display text-2xl font-bold text-slate-800">{t('prefs.title')}</h1>
        <p className="text-slate-500 text-sm mt-1">{t('prefs.subtitle')}</p>
      </div>

      <div className="bg-white rounded-3xl shadow-lg ring-1 ring-gray-100 divide-y divide-gray-100/80">

        {/* Learned Taste Graph */}
        <TasteProfileCard token={token} />

        {/* Budget Category */}
        <div className="px-6 md:px-8 py-6 space-y-5">
          <p className="text-[11px] font-semibold text-slate-400 uppercase tracking-widest mb-4">{t('prefs.budget.section')}</p>
          <div>
            <label className={labelClass}><span className="flex items-center gap-1.5"><DollarSign size={14} /> {t('prefs.budget.category')}</span></label>
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
              {BUDGET_OPTIONS.map(({ value, color }) => (
                <button key={value} type="button" data-tid={`prefs.budget-${value}`}
                  onClick={() => setPrefs(p => ({ ...p, budget_category: value }))}
                  className={`p-3 rounded-xl border-2 text-left transition-all ${prefs.budget_category === value ? `${color} ring-2 ring-offset-1 ring-current` : 'border-gray-200 hover:border-gray-300 bg-white'}`}
                >
                  <p className="font-semibold text-sm">{t(`prefs.budget.${value}.label`)}</p>
                  <p className="text-xs text-gray-500 mt-0.5">{t(`prefs.budget.${value}.desc`)}</p>
                </button>
              ))}
            </div>
          </div>
        </div>

        {/* Identity: Nationality + Residence */}
        <div className="px-6 md:px-8 py-6 space-y-5">
          <p className="text-[11px] font-semibold text-slate-400 uppercase tracking-widest mb-4">{t('prefs.identity.section')}</p>
          <NationalitySearch
            label={<span className="flex items-center gap-1.5"><Globe size={14} /> {t('prefs.identity.nationality')}</span>}
            value={prefs.nationality}
            onChange={v => setPrefs(p => ({ ...p, nationality: v }))}
            placeholder={t('prefs.identity.nationalityPlaceholder')}
          />

          <div>
            <label className={labelClass}><span className="flex items-center gap-1.5"><MapPin size={14} /> {t('prefs.identity.residence')}</span></label>
            <input
              type="text" data-tid="prefs.residence"
              value={prefs.current_residence || ''}
              onChange={e => setPrefs(p => ({ ...p, current_residence: e.target.value }))}
              placeholder={t('prefs.identity.residencePlaceholder')}
              className="w-full px-3 py-2.5 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-teal-400 bg-white"
            />
            <p className="text-xs text-gray-400 mt-1">{t('prefs.identity.residenceHint')}</p>
          </div>

          <AlertEmailField email={user?.email} emailAlertsAvailable={caps.email}
            onSave={(email) => updateAccountEmail(email, token)} onSaved={setUserEmail} />
        </div>

        {/* Documents */}
        <div className="px-6 md:px-8 py-6 space-y-5">
          <p className="text-[11px] font-semibold text-slate-400 uppercase tracking-widest mb-4">{t('prefs.documents.section')}</p>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <TagInput label={`🏠 ${t('prefs.documents.permits')}`} value={prefs.residence_permits}
              onChange={v => setPrefs(p => ({ ...p, residence_permits: v }))} placeholder={t('prefs.documents.permitsPlaceholder')} />
            <TagInput label={`📋 ${t('prefs.documents.visas')}`} value={prefs.existing_visas}
              onChange={v => setPrefs(p => ({ ...p, existing_visas: v }))} placeholder={t('prefs.documents.visasPlaceholder')} />
          </div>
        </div>

        {/* Travel Style */}
        <div className="px-6 md:px-8 py-6 space-y-5">
          <p className="text-[11px] font-semibold text-slate-400 uppercase tracking-widest mb-4">{t('prefs.style.section')}</p>

          <div>
            <label className={labelClass}><span className="flex items-center gap-1.5"><Users size={14} /> {t('prefs.style.group')}</span></label>
            <TravelerPanel form={prefs} setForm={setPrefs} />
            <p className="text-xs text-gray-400 mt-1">{t('prefs.style.groupHint')}</p>
          </div>

          <div>
            <label className={labelClass}><span className="flex items-center gap-1.5"><Heart size={14} /> {t('prefs.style.interests')}</span></label>
            <div className="flex flex-wrap gap-2">
              {INTERESTS.map(({ id, emoji }) => (
                <button key={id} type="button" data-tid={`prefs.interest-${id}`} onClick={() => toggleInterest(id)}
                  className={`px-3 py-1.5 rounded-full text-sm font-medium border-2 transition-all ${prefs.interests.includes(id) ? 'bg-teal-600 border-teal-600 text-white shadow-sm' : 'bg-white border-gray-200 text-gray-600 hover:border-teal-300 hover:text-teal-600'}`}>
                  {`${emoji} ${t(`prefs.interest.${id}`)}`}
                </button>
              ))}
            </div>
          </div>

          {/* Save */}
          <div className="flex items-center gap-3 pt-2">
            <button onClick={handleSave} disabled={saving} data-tid="prefs.save"
              className="flex items-center gap-2 px-6 py-2.5 bg-teal-600 text-white font-semibold rounded-xl hover:bg-teal-700 disabled:opacity-50 transition-all shadow-md text-sm">
              {saving ? <Loader2 size={14} className="animate-spin" /> : <Save size={14} />}
              {saving ? t('prefs.saving') : t('prefs.save')}
            </button>
            {saveMsg && (
              <span className={`flex items-center gap-1.5 text-sm font-medium ${saveIsError ? 'text-red-600' : 'text-green-600'}`}>
                {!saveIsError && <CheckCircle2 size={14} />}
                {saveMsg}
              </span>
            )}
          </div>
        </div>

        {/* Appearance: applied immediately, not part of Save */}
        <div className="px-6 md:px-8 py-6 space-y-4">
          <p className="text-[11px] font-semibold text-slate-400 uppercase tracking-widest">{tp('section.appearance')}</p>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <span className="text-sm font-medium text-gray-700">{tp('section.theme')}</span>
            <span className="flex items-center gap-1 text-sm text-slate-600">
              <ThemeToggle />
              {tc(`theme.${theme}`, { defaultValue: '' })}
            </span>
          </div>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <span className="text-sm font-medium text-gray-700">{tp('section.language')}</span>
            <LanguagePicker />
          </div>
        </div>

        {/* Privacy */}
        <div className="px-6 md:px-8 py-6 space-y-4">
          <p className="text-[11px] font-semibold text-slate-400 uppercase tracking-widest">{tp('section.privacy')}</p>
          <PrivacySwitch />
        </div>
      </div>
    </div>
  )
}
