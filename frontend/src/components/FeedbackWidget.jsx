import { useEffect, useState } from 'react'
import { useLocation } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import { MessageSquarePlus, X, Star } from 'lucide-react'
import { useTranslation } from 'react-i18next'

const PATH_TO_PAGE = {
  '/':           'search',
  '/chat':       'chat',
  '/preferences':'preferences',
  '/admin':      'admin',
}

const CATEGORIES = ['bug', 'feature_request', 'general', 'praise']
const KNOWN_PAGES = ['search', 'chat', 'preferences', 'admin']

export default function FeedbackWidget() {
  const { t } = useTranslation('misc')
  const { token } = useAuth()
  const location = useLocation()
  const [open, setOpen] = useState(false)
  const [rating, setRating]     = useState(0)
  const [hover, setHover]       = useState(0)
  const [category, setCategory] = useState('general')
  const [message, setMessage]   = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [done, setDone] = useState(false)

  const [tabs, setTabs] = useState(() => document.body.hasAttribute('data-bottom-tabs'))
  useEffect(() => {
    const sync = () => setTabs(document.body.hasAttribute('data-bottom-tabs'))
    sync()
    const mo = new MutationObserver(sync)
    mo.observe(document.body, { attributes: true, attributeFilter: ['data-bottom-tabs'] })
    return () => mo.disconnect()
  }, [])
  useEffect(() => {
    const onOpen = () => { reset(); setOpen(true) }
    window.addEventListener('voyager:open-feedback', onOpen)
    return () => window.removeEventListener('voyager:open-feedback', onOpen)
  }, [])

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
        data-tid="feedback.toggle"
        className={`fixed ${tabs ? 'bottom-20' : 'bottom-6'} left-6 z-50 hidden sm:flex items-center gap-2 px-3.5 py-2.5 bg-teal-700 hover:bg-teal-800 text-white text-sm font-medium rounded-full shadow-lg transition-all`}
        title={t('feedback.triggerTitle')}
      >
        {open ? <X size={15} /> : <MessageSquarePlus size={15} />}
        <span className="hidden sm:inline">{open ? t('feedback.close') : t('feedback.trigger')}</span>
      </button>

      {/* Panel */}
      {open && (
        <div className={`fixed ${tabs ? 'bottom-36' : 'bottom-20'} left-6 z-50 w-80 max-w-[calc(100vw-3rem)] bg-white rounded-2xl shadow-2xl border border-gray-200 overflow-hidden`}>
          {done ? (
            <div className="p-6 text-center">
              <div className="text-3xl mb-2">🙏</div>
              <p className="font-semibold text-gray-800">{t('feedback.thanks')}</p>
              <p className="text-sm text-gray-500 mt-1">{t('feedback.thanksBody')}</p>
            </div>
          ) : (
            <>
              <div className="px-4 py-3 bg-teal-50 border-b border-teal-100 flex items-center justify-between">
                <span className="text-sm font-semibold text-teal-800 capitalize">
                  {t('feedback.panelTitle', { page: t(`feedback.page.${KNOWN_PAGES.includes(page) ? page : 'other'}`) })}
                </span>
                <button onClick={handleClose} data-tid="feedback.close" aria-label={t('feedback.close')} className="text-teal-500 hover:text-teal-700">
                  <X size={14} />
                </button>
              </div>

              <div className="p-4 space-y-3">
                {/* Star rating */}
                <div>
                  <p className="text-xs font-medium text-gray-600 mb-1.5">{t('feedback.rate')}</p>
                  <div className="flex gap-1">
                    {[1, 2, 3, 4, 5].map(s => (
                      <button
                        key={s}
                        data-tid={`feedback.star-${s}`}
                        aria-label={t('feedback.star', { count: s })}
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
                  <label className="text-xs font-medium text-gray-600 block mb-1">{t('feedback.category')}</label>
                  <select
                    value={category}
                    onChange={e => setCategory(e.target.value)}
                    className="w-full px-2.5 py-1.5 text-sm border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-teal-400"
                  >
                    {CATEGORIES.map(c => (
                      <option key={c} value={c}>{t(`feedback.cat.${c}`)}</option>
                    ))}
                  </select>
                </div>

                {/* Message */}
                <div>
                  <label className="text-xs font-medium text-gray-600 block mb-1">
                    {t('feedback.message')} <span className="text-gray-400">{t('feedback.optional')}</span>
                  </label>
                  <textarea
                    value={message}
                    onChange={e => setMessage(e.target.value.slice(0, 500))}
                    rows={3}
                    placeholder={t('feedback.placeholder')}
                    className="w-full px-2.5 py-1.5 text-sm border border-gray-300 rounded-lg resize-none focus:outline-none focus:ring-2 focus:ring-teal-400"
                  />
                  <p className="text-right text-xs text-gray-400 mt-0.5">{message.length}/500</p>
                </div>

                <button
                  onClick={submit}
                  data-tid="feedback.send"
                  disabled={!rating || submitting}
                  className="w-full py-2 bg-teal-600 hover:bg-teal-700 disabled:bg-teal-200 disabled:text-teal-400 text-white text-sm font-semibold rounded-lg transition-colors"
                >
                  {submitting ? t('feedback.sending') : t('feedback.send')}
                </button>
              </div>
            </>
          )}
        </div>
      )}
    </>
  )
}
