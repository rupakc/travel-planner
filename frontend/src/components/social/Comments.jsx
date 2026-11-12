import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useAuth } from '../../context/AuthContext'
import {
  addComment, deleteComment, listComments, markHelpful, unmarkHelpful,
} from '../../services/socialApi'
import Handle from './Handle'
import ReportDialog from './ReportDialog'
import { btn, btnPrimary, field, socialError } from './ui'
import { track } from './track'

const MAX = 300

/**
 * Comments of one idea (oldest first). All text is rendered as plain text nodes.
 * Props: ideaId, ideaMine (the viewer wrote the idea: may mark helpful and delete any comment), onCount(delta).
 */
export default function Comments({ ideaId, ideaMine = false, onCount }) {
  const { t } = useTranslation('social')
  const { token } = useAuth()
  const [items, setItems] = useState([])
  const [next, setNext] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(false)
  const [reporting, setReporting] = useState(null)

  const load = useCallback(async (cursor) => {
    setLoading(true); setError('')
    try {
      const r = await listComments(token, ideaId, cursor)
      setItems((cur) => (cursor ? [...cur, ...(r?.comments || [])] : (r?.comments || [])))
      setNext(r?.next ?? null)
    } catch (e) {
      setError(socialError(t, e))
    } finally { setLoading(false) }
  }, [token, ideaId, t])

  useEffect(() => { load(null) }, [load])

  const submit = async (e) => {
    e.preventDefault()
    const body = text.trim()
    if (!body) return
    setBusy(true); setError('')
    try {
      const c = await addComment(token, ideaId, body)
      track('social_comment')
      setItems((cur) => [...cur, c])
      setText('')
      onCount?.(1)
    } catch (err) {
      setError(socialError(t, err))
    } finally { setBusy(false) }
  }

  const remove = async (c) => {
    setError('')
    try {
      await deleteComment(token, c.id)
      setItems((cur) => cur.filter((x) => x.id !== c.id))
      onCount?.(-1)
    } catch (err) { setError(socialError(t, err)) }
  }

  const helpful = async (c) => {
    setError('')
    try {
      await (c.helpful ? unmarkHelpful(token, c.id) : markHelpful(token, c.id))
      setItems((cur) => cur.map((x) => (x.id === c.id ? { ...x, helpful: !c.helpful } : x)))
    } catch (err) { setError(socialError(t, err)) }
  }

  return (
    <section aria-label={t('comments.title')} data-tid="social.comments" className="space-y-3 border-t border-border pt-3">
      {error && <p role="alert" data-tid="social.comments.error" className="text-sm text-red-600">{error}</p>}
      {!loading && !items.length && !error && (
        <p data-tid="social.comments.empty" className="text-sm text-text-muted">{t('comments.empty')}</p>
      )}
      <ul className="space-y-3">
        {items.map((c) => (
          <li key={c.id} data-tid="social.comment" className="space-y-1">
            <div className="flex flex-wrap items-center gap-2 text-xs text-text-muted">
              <Handle handle={c.author?.handle} className="text-text" tid="social.comment.author" />
              {c.helpful && <span data-tid="social.comment.helpful" className="rounded-full bg-teal-100 px-2 py-0.5 text-teal-800">{t('comments.helpful')}</span>}
              {c.status === 'held' && <span data-tid="social.comment.held" className="rounded-full bg-amber-100 px-2 py-0.5 text-amber-800">{t('comments.held')}</span>}
            </div>
            <p className="whitespace-pre-wrap break-words text-sm text-text" data-tid="social.comment.text">{c.text}</p>
            <div className="flex flex-wrap gap-1">
              {ideaMine && !c.mine && (
                <button type="button" onClick={() => helpful(c)} aria-pressed={!!c.helpful} data-tid="social.comment.markHelpful"
                  className={`${btn} text-xs`}>
                  {c.helpful ? t('comments.unmarkHelpful') : t('comments.markHelpful')}
                </button>
              )}
              {(c.mine || ideaMine) && (
                <button type="button" onClick={() => remove(c)} data-tid="social.comment.delete" className={`${btn} text-xs`}>{t('comments.delete')}</button>
              )}
              {!c.mine && (
                <button type="button" onClick={() => setReporting(c.id)} data-tid="social.comment.report" className={`${btn} text-xs`}>{t('idea.report')}</button>
              )}
            </div>
          </li>
        ))}
      </ul>
      {next && (
        <button type="button" disabled={loading} onClick={() => load(next)} data-tid="social.comments.more" className={btn}>{t('comments.more')}</button>
      )}
      <form onSubmit={submit} className="space-y-2">
        <label htmlFor={`comment-${ideaId}`} className="block text-xs text-text-muted">{t('comments.label')}</label>
        <textarea id={`comment-${ideaId}`} value={text} maxLength={MAX} rows={2} data-tid="social.comments.input"
          onChange={(e) => setText(e.target.value)} className={`${field} py-2`} />
        <div className="flex items-center justify-between gap-2">
          <span className="text-xs text-text-muted">{t('comments.counter', { n: text.length, max: MAX })}</span>
          <button type="submit" disabled={busy || !text.trim()} data-tid="social.comments.post" className={btnPrimary}>{t('comments.post')}</button>
        </div>
      </form>
      {reporting != null && <ReportDialog target="comment" id={reporting} onClose={() => setReporting(null)} />}
    </section>
  )
}
