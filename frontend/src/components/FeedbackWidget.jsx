import { useState } from 'react'
import { useLocation } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import { MessageSquarePlus, X, Star } from 'lucide-react'

const PATH_TO_PAGE = {
  '/':           'search',
  '/chat':       'chat',
  '/preferences':'preferences',
  '/admin':      'admin',
}

const CATEGORIES = [
  { value: 'bug',             label: 'Bug report' },
  { value: 'feature_request', label: 'Feature request' },
  { value: 'general',         label: 'General feedback' },
  { value: 'praise',          label: 'Praise' },
]

export default function FeedbackWidget() {
  const { token } = useAuth()
  const location = useLocation()
  const [open, setOpen] = useState(false)
  const [rating, setRating]     = useState(0)
  const [hover, setHover]       = useState(0)
  const [category, setCategory] = useState('general')
  const [message, setMessage]   = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [done, setDone] = useState(false)

  const page = PATH_TO_PAGE[location.pathname] ?? 'other'

  const reset = () => {
    setRating(0); setHover(0); setCategory('general'); setMessage('')
    setDone(false)
  }

  const handleOpen = () => { reset(); setOpen(true) }
  const handleClose = () => { setOpen(false); reset() }

  const submit = async () => {
    if (!rating) return
    setSubmitting(true)
    try {
      await fetch('/api/feedback', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify({
          page,
          rating,
          category,
          message: message.trim() || null,
          metadata: { viewport: window.innerWidth },
        }),
      })
      setDone(true)
      setTimeout(handleClose, 2000)
    } catch {
      // silently fail — feedback is non-critical
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <>
      {/* Floating trigger button */}
      <button
        onClick={open ? handleClose : handleOpen}
        className="fixed bottom-6 left-6 z-50 flex items-center gap-2 px-3.5 py-2.5 bg-teal-600 hover:bg-teal-700 text-white text-sm font-medium rounded-full shadow-lg transition-all"
        title="Give feedback"
      >
        {open ? <X size={15} /> : <MessageSquarePlus size={15} />}
        <span className="hidden sm:inline">{open ? 'Close' : 'Feedback'}</span>
      </button>

      {/* Panel */}
      {open && (
        <div className="fixed bottom-20 left-6 z-50 w-80 bg-white rounded-2xl shadow-2xl border border-gray-200 overflow-hidden">
          {done ? (
            <div className="p-6 text-center">
              <div className="text-3xl mb-2">🙏</div>
              <p className="font-semibold text-gray-800">Thank you!</p>
              <p className="text-sm text-gray-500 mt-1">Your feedback helps us improve.</p>
            </div>
          ) : (
            <>
              <div className="px-4 py-3 bg-teal-50 border-b border-teal-100 flex items-center justify-between">
                <span className="text-sm font-semibold text-teal-800 capitalize">
                  Feedback on {page}
                </span>
                <button onClick={handleClose} className="text-teal-500 hover:text-teal-700">
                  <X size={14} />
                </button>
              </div>

              <div className="p-4 space-y-3">
                {/* Star rating */}
                <div>
                  <p className="text-xs font-medium text-gray-600 mb-1.5">How would you rate this?</p>
                  <div className="flex gap-1">
                    {[1, 2, 3, 4, 5].map(s => (
                      <button
                        key={s}
                        onMouseEnter={() => setHover(s)}
                        onMouseLeave={() => setHover(0)}
                        onClick={() => setRating(s)}
                        className="transition-transform hover:scale-110"
                      >
                        <Star
                          size={24}
                          className={s <= (hover || rating) ? 'text-yellow-400 fill-yellow-400' : 'text-gray-300'}
                        />
                      </button>
                    ))}
                  </div>
                </div>

                {/* Category */}
                <div>
                  <label className="text-xs font-medium text-gray-600 block mb-1">Category</label>
                  <select
                    value={category}
                    onChange={e => setCategory(e.target.value)}
                    className="w-full px-2.5 py-1.5 text-sm border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-teal-400"
                  >
                    {CATEGORIES.map(c => (
                      <option key={c.value} value={c.value}>{c.label}</option>
                    ))}
                  </select>
                </div>

                {/* Message */}
                <div>
                  <label className="text-xs font-medium text-gray-600 block mb-1">
                    Message <span className="text-gray-400">(optional)</span>
                  </label>
                  <textarea
                    value={message}
                    onChange={e => setMessage(e.target.value.slice(0, 500))}
                    rows={3}
                    placeholder="Tell us more…"
                    className="w-full px-2.5 py-1.5 text-sm border border-gray-300 rounded-lg resize-none focus:outline-none focus:ring-2 focus:ring-teal-400"
                  />
                  <p className="text-right text-xs text-gray-400 mt-0.5">{message.length}/500</p>
                </div>

                <button
                  onClick={submit}
                  disabled={!rating || submitting}
                  className="w-full py-2 bg-teal-600 hover:bg-teal-700 disabled:bg-teal-200 disabled:text-teal-400 text-white text-sm font-semibold rounded-lg transition-colors"
                >
                  {submitting ? 'Sending…' : 'Send feedback'}
                </button>
              </div>
            </>
          )}
        </div>
      )}
    </>
  )
}
