import { useState, useEffect, useRef } from 'react'
import { Users, ChevronDown, ChevronUp, Plus, Minus } from 'lucide-react'
import { useTranslation } from 'react-i18next'

const ACCESSIBILITY_IDS = ['wheelchair', 'visual_impairment', 'hearing_impairment', 'cognitive_disability']

const ACCESS_EMOJI = {
  wheelchair:           '♿',
  visual_impairment:    '👁️',
  hearing_impairment:   '🦻',
  cognitive_disability: '🧠',
}

export default function TravelerPanel({ form, setForm }) {
  const { t } = useTranslation('search')
  const [open, setOpen] = useState(false)
  const panelRef = useRef(null)

  useEffect(() => {
    if (!open) return
    const handler = (e) => {
      if (panelRef.current && !panelRef.current.contains(e.target)) setOpen(false)
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [open])

  const counts = [
    { key: 'adults',   label: t('travelers.adults'),   sub: '18–64' },
    { key: 'seniors',  label: t('travelers.seniors'),  sub: '65+' },
    { key: 'children', label: t('travelers.children'), sub: '5–17' },
    { key: 'infants',  label: t('travelers.infants'),  sub: '0–4' },
  ]

  const total = (form.adults || 0) + (form.seniors || 0) + (form.children || 0) + (form.infants || 0)
  const chips = []
  if (form.adults)   chips.push(`${form.adults}👤`)
  if (form.seniors)  chips.push(`${form.seniors}🧓`)
  if (form.children) chips.push(`${form.children}🧒`)
  if (form.infants)  chips.push(`${form.infants}👶`)
  const accessEmojis = (form.accessibility_needs || []).map(id => ACCESS_EMOJI[id] || '').filter(Boolean)

  const change = (key, delta) => {
    setForm(f => {
      const next = Math.max(0, (f[key] || 0) + delta)
      const newTotal =
        (key === 'adults'   ? next : (f.adults   || 0)) +
        (key === 'seniors'  ? next : (f.seniors  || 0)) +
        (key === 'children' ? next : (f.children || 0)) +
        (key === 'infants'  ? next : (f.infants  || 0))
      if (newTotal < 1) return f
      return { ...f, [key]: next }
    })
  }

  const toggleAccess = (id) => {
    setForm(f => ({
      ...f,
      accessibility_needs: (f.accessibility_needs || []).includes(id)
        ? (f.accessibility_needs || []).filter(x => x !== id)
        : [...(f.accessibility_needs || []), id],
    }))
  }

  return (
    <div className="relative" ref={panelRef}>
      <button
        type="button" data-tid="search.travelers-toggle"
        onClick={() => setOpen(o => !o)}
        className="w-full flex items-center justify-between px-3 py-2.5 border border-gray-200 rounded-lg bg-white hover:bg-gray-50 transition-colors"
      >
        <div className="flex items-center gap-1.5 min-w-0 flex-1 overflow-hidden">
          <Users size={13} className="text-gray-500 shrink-0" />
          <span className="text-sm text-gray-700 whitespace-nowrap">
            {chips.length ? chips.join(' ') : t('travelers.total', { count: total })}
            {accessEmojis.length > 0 && <span className="text-teal-600"> {accessEmojis.join('')}</span>}
          </span>
        </div>
        {open ? <ChevronUp size={14} className="text-gray-400 shrink-0" /> : <ChevronDown size={14} className="text-gray-400 shrink-0" />}
      </button>

      {open && (
        <div className="absolute top-full left-0 right-0 z-50 mt-1 bg-white border border-gray-200 rounded-lg shadow-xl px-3 py-3 space-y-3">
          {counts.map(({ key, label, sub }) => (
            <div key={key} className="flex items-center justify-between">
              <div>
                <span className="text-sm font-medium text-gray-700">{label}</span>
                <span className="text-xs text-gray-400 ml-1">({sub})</span>
              </div>
              <div className="flex items-center gap-2">
                <button
                  type="button" data-tid={`search.travelers-${key}-minus`}
                  aria-label={t('travelers.fewer', { group: label })}
                  onClick={() => change(key, -1)}
                  disabled={!form[key] || (key === 'adults' && total <= 1 && (form[key] || 0) <= 1)}
                  className="w-7 h-7 flex items-center justify-center rounded-full border border-gray-200 bg-gray-50 hover:bg-gray-100 disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
                >
                  <Minus size={12} />
                </button>
                <span className="w-5 text-center text-sm font-semibold text-gray-800">{form[key] || 0}</span>
                <button
                  type="button" data-tid={`search.travelers-${key}-plus`}
                  aria-label={t('travelers.more', { group: label })}
                  onClick={() => change(key, 1)}
                  className="w-7 h-7 flex items-center justify-center rounded-full border border-teal-200 bg-teal-50 hover:bg-teal-100 transition-colors text-teal-700"
                >
                  <Plus size={12} />
                </button>
              </div>
            </div>
          ))}

          <div className="pt-2 border-t border-gray-100">
            <p className="text-xs font-medium text-gray-600 mb-2">{t('travelers.accessibility')}</p>
            <div className="space-y-1.5">
              {ACCESSIBILITY_IDS.map((id) => (
                <label key={id} className="flex items-center gap-2 cursor-pointer">
                  <input
                    type="checkbox" data-tid={`search.travelers-access-${id}`}
                    checked={(form.accessibility_needs || []).includes(id)}
                    onChange={() => toggleAccess(id)}
                    className="w-4 h-4 rounded border-gray-300 text-teal-600 focus:ring-teal-400"
                  />
                  <span className="text-sm text-gray-700">{t(`travelers.access.${id}`)}</span>
                </label>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
