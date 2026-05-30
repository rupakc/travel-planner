import { useState, useEffect } from 'react'
import { useAuth } from '../context/AuthContext'
import NationalitySearch from '../components/ui/NationalitySearch'
import { track } from '../utils/analytics'
import TagInput from '../components/ui/TagInput'
import { Save, Loader2, CheckCircle2, Globe, DollarSign, Users, Heart, MapPin } from 'lucide-react'

const BUDGET_OPTIONS = [
  { value: 'low',    label: 'Budget',   desc: 'Hostels, street food, public transport',     color: 'bg-green-100 text-green-700 border-green-300' },
  { value: 'medium', label: 'Mid-range', desc: 'Comfortable hotels, nice restaurants',       color: 'bg-teal-50 text-teal-700 border-teal-300' },
  { value: 'high',   label: 'Luxury',    desc: 'Premium hotels, fine dining, private tours', color: 'bg-purple-100 text-purple-700 border-purple-300' },
]

const INTERESTS = [
  { id: 'food',      label: '🍜 Food' },
  { id: 'history',   label: '🏛️ History' },
  { id: 'adventure', label: '🧗 Adventure' },
  { id: 'culture',   label: '🎭 Culture' },
  { id: 'nature',    label: '🌿 Nature' },
  { id: 'shopping',  label: '🛍️ Shopping' },
  { id: 'nightlife', label: '🌙 Nightlife' },
  { id: 'wellness',  label: '🧘 Wellness' },
  { id: 'art',       label: '🎨 Art' },
  { id: 'family',    label: '👨‍👩‍👧 Family' },
]

export default function PreferencesPage() {
  const { token, refreshPreferences } = useAuth()
  const [prefs, setPrefs] = useState(null)
  const [saving, setSaving] = useState(false)
  const [saveMsg, setSaveMsg] = useState('')
  const [loading, setLoading] = useState(true)
  const [visitedDestinations, setVisitedDestinations] = useState([])

  useEffect(() => {
    if (!token) return
    fetch('/api/preferences', { headers: { Authorization: `Bearer ${token}` } })
      .then(r => r.ok ? r.json() : Promise.reject())
      .then(data => {
        setPrefs(data)
        setVisitedDestinations(data.visited_destinations || [])
      })
      .catch(() => setPrefs({
        budget_category: 'medium', nationality: '', current_residence: '',
        residence_permits: [], existing_visas: [],
        interests: [], num_travelers: 1,
      }))
      .finally(() => setLoading(false))
  }, [token])

  const handleSave = async () => {
    setSaving(true); setSaveMsg('')
    try {
      const res = await fetch('/api/preferences', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify({ ...prefs, visited_destinations: visitedDestinations }),
      })
      if (res.ok) {
        refreshPreferences()
        track('preferences_saved', 'preferences')
        setSaveMsg('Preferences saved!')
        setTimeout(() => setSaveMsg(''), 3000)
      } else {
        const err = await res.json()
        setSaveMsg(`Error: ${err.detail || 'Save failed'}`)
      }
    } catch { setSaveMsg('Save failed') }
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
        <h1 className="font-display text-2xl font-bold text-slate-800">Travel Preferences</h1>
        <p className="text-slate-500 text-sm mt-1">Set your defaults to pre-fill the search form and get personalized results.</p>
      </div>

      <div className="bg-white rounded-3xl shadow-lg ring-1 ring-gray-100 divide-y divide-gray-100/80">

        {/* Budget Category */}
        <div className="px-6 md:px-8 py-6 space-y-5">
          <p className="text-[11px] font-semibold text-slate-400 uppercase tracking-widest mb-4">Travel Budget</p>
          <div>
            <label className={labelClass}><span className="flex items-center gap-1.5"><DollarSign size={14} /> Budget Category</span></label>
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
              {BUDGET_OPTIONS.map(({ value, label, desc, color }) => (
                <button key={value} type="button"
                  onClick={() => setPrefs(p => ({ ...p, budget_category: value }))}
                  className={`p-3 rounded-xl border-2 text-left transition-all ${prefs.budget_category === value ? `${color} ring-2 ring-offset-1 ring-current` : 'border-gray-200 hover:border-gray-300 bg-white'}`}
                >
                  <p className="font-semibold text-sm">{label}</p>
                  <p className="text-xs text-gray-500 mt-0.5">{desc}</p>
                </button>
              ))}
            </div>
          </div>
        </div>

        {/* Identity: Nationality + Residence */}
        <div className="px-6 md:px-8 py-6 space-y-5">
          <p className="text-[11px] font-semibold text-slate-400 uppercase tracking-widest mb-4">Identity</p>
          <NationalitySearch
            label={<span className="flex items-center gap-1.5"><Globe size={14} /> Nationality</span>}
            value={prefs.nationality}
            onChange={v => setPrefs(p => ({ ...p, nationality: v }))}
            placeholder="American, Indian, British…"
          />

          <div>
            <label className={labelClass}><span className="flex items-center gap-1.5"><MapPin size={14} /> Current Residence</span></label>
            <input
              type="text"
              value={prefs.current_residence || ''}
              onChange={e => setPrefs(p => ({ ...p, current_residence: e.target.value }))}
              placeholder="e.g. Munich, Germany"
              className="w-full px-3 py-2.5 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-teal-400 bg-white"
            />
            <p className="text-xs text-gray-400 mt-1">Used as default departure city when planning trips</p>
          </div>
        </div>

        {/* Documents */}
        <div className="px-6 md:px-8 py-6 space-y-5">
          <p className="text-[11px] font-semibold text-slate-400 uppercase tracking-widest mb-4">Documents</p>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <TagInput label="🏠 Residence Permits" value={prefs.residence_permits}
              onChange={v => setPrefs(p => ({ ...p, residence_permits: v }))} placeholder="Schengen, UK, UAE…" />
            <TagInput label="📋 Existing Visas" value={prefs.existing_visas}
              onChange={v => setPrefs(p => ({ ...p, existing_visas: v }))} placeholder="US, Japan, Canada…" />
          </div>
        </div>

        {/* Travel Style */}
        <div className="px-6 md:px-8 py-6 space-y-5">
          <p className="text-[11px] font-semibold text-slate-400 uppercase tracking-widest mb-4">Travel Style</p>

          <div>
            <label className={labelClass}><span className="flex items-center gap-1.5"><Users size={14} /> Default Number of Travelers</span></label>
            <div className="inline-flex items-center border border-gray-300 rounded-lg overflow-hidden bg-white">
              <button type="button" onClick={() => setPrefs(p => ({ ...p, num_travelers: Math.max(1, p.num_travelers - 1) }))}
                className="px-3 py-2.5 bg-gray-50 hover:bg-gray-100 text-gray-600 font-bold text-lg leading-none">−</button>
              <span className="flex-1 text-center text-sm font-medium py-2.5">{prefs.num_travelers}</span>
              <button type="button" onClick={() => setPrefs(p => ({ ...p, num_travelers: Math.min(20, p.num_travelers + 1) }))}
                className="px-3 py-2.5 bg-gray-50 hover:bg-gray-100 text-gray-600 font-bold text-lg leading-none">+</button>
            </div>
          </div>

          <div>
            <label className={labelClass}><span className="flex items-center gap-1.5"><Heart size={14} /> Interests</span></label>
            <div className="flex flex-wrap gap-2">
              {INTERESTS.map(({ id, label }) => (
                <button key={id} type="button" onClick={() => toggleInterest(id)}
                  className={`px-3 py-1.5 rounded-full text-sm font-medium border-2 transition-all ${prefs.interests.includes(id) ? 'bg-teal-600 border-teal-600 text-white shadow-sm' : 'bg-white border-gray-200 text-gray-600 hover:border-teal-300 hover:text-teal-600'}`}>
                  {label}
                </button>
              ))}
            </div>
          </div>

          <div>
            <label className={labelClass}><span className="flex items-center gap-1.5"><MapPin size={14} /> Places You Have Visited</span></label>
            <p className="text-xs text-gray-400 mb-2">We will skip tourist basics on repeat visits</p>
            <TagInput
              value={visitedDestinations}
              onChange={setVisitedDestinations}
              placeholder="Tokyo, Paris, Bali..."
            />
          </div>

          {/* Save */}
          <div className="flex items-center gap-3 pt-2">
            <button onClick={handleSave} disabled={saving}
              className="flex items-center gap-2 px-6 py-2.5 bg-teal-600 text-white font-semibold rounded-xl hover:bg-teal-700 disabled:opacity-50 transition-all shadow-md text-sm">
              {saving ? <Loader2 size={14} className="animate-spin" /> : <Save size={14} />}
              {saving ? 'Saving…' : 'Save Preferences'}
            </button>
            {saveMsg && (
              <span className={`flex items-center gap-1.5 text-sm font-medium ${saveMsg.startsWith('Error') ? 'text-red-600' : 'text-green-600'}`}>
                {!saveMsg.startsWith('Error') && <CheckCircle2 size={14} />}
                {saveMsg}
              </span>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
