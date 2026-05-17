import { useState, useRef, useEffect, useCallback } from 'react'
import { Globe, X, Loader2 } from 'lucide-react'

export default function NationalitySearch({ label, value, onChange, placeholder = 'Search nationality…', required = false }) {
  const [displayText, setDisplayText] = useState('')
  const [results, setResults] = useState([])
  const [isOpen, setIsOpen] = useState(false)
  const [isLoading, setIsLoading] = useState(false)
  const [highlightIdx, setHighlightIdx] = useState(-1)
  const debounceRef = useRef(null)
  const containerRef = useRef(null)
  const inputRef = useRef(null)

  // Sync display when value changes externally (e.g. preference pre-fill)
  useEffect(() => {
    setDisplayText(value || '')
  }, [value])

  const doSearch = useCallback(async (q) => {
    if (q.length < 1) { setResults([]); setIsOpen(false); return }
    setIsLoading(true)
    try {
      const res = await fetch(`/api/nationalities/search?q=${encodeURIComponent(q)}&limit=10`)
      const data = await res.json()
      setResults(Array.isArray(data) ? data : [])
      setIsOpen(Array.isArray(data) && data.length > 0)
      setHighlightIdx(-1)
    } catch { setResults([]) }
    finally { setIsLoading(false) }
  }, [])

  const handleChange = (e) => {
    const q = e.target.value
    setDisplayText(q)
    onChange(q)
    if (debounceRef.current) clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(() => doSearch(q), 200)
  }

  const handleSelect = (nat) => {
    setDisplayText(nat.nationality)
    onChange(nat.nationality)
    setResults([]); setIsOpen(false)
    inputRef.current?.blur()
  }

  const handleClear = () => {
    setDisplayText(''); onChange(''); setResults([]); setIsOpen(false)
    inputRef.current?.focus()
  }

  const handleKeyDown = (e) => {
    if (!isOpen || !results.length) return
    if (e.key === 'ArrowDown') { e.preventDefault(); setHighlightIdx(i => Math.min(i + 1, results.length - 1)) }
    else if (e.key === 'ArrowUp') { e.preventDefault(); setHighlightIdx(i => Math.max(i - 1, 0)) }
    else if (e.key === 'Enter' && highlightIdx >= 0) { e.preventDefault(); handleSelect(results[highlightIdx]) }
    else if (e.key === 'Escape') { setIsOpen(false) }
  }

  // Close on outside click
  useEffect(() => {
    const h = (e) => { if (containerRef.current && !containerRef.current.contains(e.target)) setIsOpen(false) }
    document.addEventListener('mousedown', h)
    return () => document.removeEventListener('mousedown', h)
  }, [])

  return (
    <div ref={containerRef} className="relative">
      {label && (
        <label className="block text-sm font-medium text-gray-700 mb-1">
          {label}{required && <span className="text-red-500 ml-0.5">*</span>}
        </label>
      )}
      <div className="relative">
        <input
          ref={inputRef}
          type="text"
          value={displayText}
          onChange={handleChange}
          onKeyDown={handleKeyDown}
          onFocus={() => results.length > 0 && setIsOpen(true)}
          placeholder={placeholder}
          required={required}
          autoComplete="off"
          className="w-full px-3 py-2.5 pl-9 pr-8 border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-teal-400 focus:border-teal-400 transition-colors text-sm bg-white"
        />
        <Globe size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400 pointer-events-none" />
        <div className="absolute right-2.5 top-1/2 -translate-y-1/2">
          {isLoading
            ? <Loader2 size={14} className="text-gray-400 animate-spin" />
            : displayText
              ? <button type="button" onClick={handleClear} className="text-gray-400 hover:text-gray-600 transition-colors"><X size={14} /></button>
              : null}
        </div>
      </div>

      {isOpen && results.length > 0 && (
        <ul className="absolute z-50 w-full mt-1 bg-white border border-gray-200 rounded-xl shadow-2xl overflow-hidden max-h-72 overflow-y-auto divide-y divide-gray-50">
          {results.map((nat, idx) => (
            <li key={nat.nationality}>
              <button
                type="button"
                onMouseDown={(e) => { e.preventDefault(); handleSelect(nat) }}
                className={`w-full flex items-center gap-3 px-4 py-2.5 text-left transition-colors ${idx === highlightIdx ? 'bg-teal-50' : 'hover:bg-gray-50'}`}
              >
                <span className="w-8 shrink-0 text-xs font-bold text-teal-700 bg-teal-100 rounded-md px-1.5 py-0.5 text-center">
                  {nat.country_code}
                </span>
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-medium text-gray-900">{nat.nationality}</p>
                  <p className="text-xs text-gray-500">{nat.country}</p>
                </div>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
