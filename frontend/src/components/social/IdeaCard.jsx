import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { Heart, Bookmark, MessageCircle, Flag, Trash2 } from 'lucide-react'
import { useAuth } from '../../context/AuthContext'
import { deleteIdea, likeIdea, saveIdea, unlikeIdea } from '../../services/socialApi'
import Handle from './Handle'
import Comments from './Comments'
import ReportDialog from './ReportDialog'
import { btn, card, socialError } from './ui'
import { feedPath } from './paths'
import { track } from './track'

const STAT_KEYS = ['activities', 'hotels', 'places']
const ITEM_GROUPS = ['activities', 'places_to_see', 'hotels', 'walking_tours', 'events']
const SHOWN_ITEMS = 6

// An avatar URL comes from the server; accept only an own-origin path or https.
const safeAvatar = (u) => (typeof u === 'string' && (/^\/(?!\/)/.test(u) || /^https:\/\//i.test(u)) ? u : null)

/**
 * One idea. Every string (title, caption, names, comments) is rendered as a plain
 * text node: no HTML, no markdown, no auto-links.
 * Props: idea, onChange(updated idea), onDeleted(id), expanded (open the comments), link (title links to /feed/<id>).
 */
export default function IdeaCard({ idea, onChange, onDeleted, expanded = false, link = true }) {
  const { t } = useTranslation('social')
  const { token } = useAuth()
  const [showComments, setShowComments] = useState(expanded)
  const [reporting, setReporting] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [busy, setBusy] = useState(false)
  const snap = idea.snapshot || {}
  const stats = Array.isArray(snap.stats) ? snap.stats.filter((s) => STAT_KEYS.includes(s?.key)) : []
  const names = ITEM_GROUPS.flatMap((g) => (Array.isArray(snap.items?.[g]) ? snap.items[g] : []))
    .map((i) => (typeof i?.name === 'string' ? i.name : null)).filter(Boolean)
  const dests = Array.isArray(snap.destinations) ? snap.destinations.filter((d) => typeof d === 'string') : []
  const avatar = safeAvatar(idea.author?.avatar_url)
  const patch = (p) => onChange?.({ ...idea, ...p })

  const like = async () => {
    const on = !idea.liked
    setError('')
    patch({ liked: on, likes: Math.max(0, (idea.likes || 0) + (on ? 1 : -1)) }) // optimistic
    try {
      await (on ? likeIdea(token, idea.id) : unlikeIdea(token, idea.id))
      track('social_idea_like', { on })
    } catch (e) {
      patch({ liked: !on, likes: idea.likes || 0 })
      setError(socialError(t, e))
    }
  }

  const save = async () => {
    setBusy(true); setError(''); setNotice('')
    try {
      await saveIdea(token, idea.id)
      track('social_idea_save')
      patch({ saved: true, saves: (idea.saves || 0) + (idea.saved ? 0 : 1) })
      setNotice(t('idea.savedNote'))
    } catch (e) {
      setError(socialError(t, e))
    } finally { setBusy(false) }
  }

  const remove = async () => {
    setBusy(true); setError('')
    try {
      await deleteIdea(token, idea.id)
      onDeleted?.(idea.id)
    } catch (e) {
      setError(socialError(t, e)); setBusy(false)
    }
  }

  const title = <span data-tid="social.idea.title">{idea.title}</span>
  return (
    <article className={`${card} space-y-3`} data-tid="social.idea" aria-label={idea.title}>
      <header className="flex flex-wrap items-center gap-2 text-sm text-text-muted">
        {avatar && <img src={avatar} alt="" width={24} height={24} className="h-6 w-6 rounded-full object-cover" />}
        <span>{t('idea.by')}</span>
        <Handle handle={idea.author?.handle} className="text-text" tid="social.idea.author" />
        <span className="rounded-full bg-surface px-2 py-0.5 text-xs" data-tid="social.idea.kind">{t(`idea.kind.${idea.kind === 'recap' ? 'recap' : 'plan'}`)}</span>
        {idea.status === 'held' && (
          <span className="rounded-full bg-amber-100 px-2 py-0.5 text-xs text-amber-800" data-tid="social.idea.held">{t('idea.held')}</span>
        )}
      </header>

      <h3 className="text-lg font-semibold text-text break-words">
        {link ? <Link to={feedPath(idea.id)} data-tid="social.idea.open" className="inline-flex min-h-[44px] items-center hover:underline">{title}</Link> : title}
      </h3>
      {idea.caption && <p className="whitespace-pre-wrap break-words text-sm text-text" data-tid="social.idea.caption">{idea.caption}</p>}

      {(dests.length > 0 || snap.days > 0 || stats.length > 0) && (
        <p className="flex flex-wrap gap-x-3 gap-y-1 text-xs text-text-muted" data-tid="social.idea.facts">
          {dests.length > 0 && <span>{dests.join(' · ')}</span>}
          {snap.days > 0 && <span>{t('idea.tripDays', { days: snap.days })}</span>}
          {stats.map((s) => <span key={s.key}>{t(`idea.stats.${s.key}`)} {s.count}</span>)}
        </p>
      )}
      {names.length > 0 && (
        <div>
          <h4 className="text-xs font-medium text-text-muted">{t('idea.itemsHeading')}</h4>
          <ul className="mt-1 list-disc space-y-0.5 pl-5 text-sm text-text" data-tid="social.idea.items">
            {names.slice(0, SHOWN_ITEMS).map((n, i) => <li key={`${i}-${n}`} className="break-words">{n}</li>)}
          </ul>
          {names.length > SHOWN_ITEMS && <p className="mt-1 text-xs text-text-muted">{t('idea.moreItems', { n: names.length - SHOWN_ITEMS })}</p>}
        </div>
      )}

      <div className="flex flex-wrap gap-2">
        <button type="button" onClick={like} aria-pressed={!!idea.liked} data-tid="social.idea.like" className={`${btn} inline-flex items-center gap-1.5`}>
          <Heart size={16} aria-hidden="true" fill={idea.liked ? 'currentColor' : 'none'} />
          <span>{idea.liked ? t('idea.unlike') : t('idea.like')}</span>
          <span data-tid="social.idea.likes">{idea.likes || 0}</span>
        </button>
        {!idea.mine && (
          <button type="button" onClick={save} disabled={busy} data-tid="social.idea.save" className={`${btn} inline-flex items-center gap-1.5`}>
            <Bookmark size={16} aria-hidden="true" fill={idea.saved ? 'currentColor' : 'none'} />
            <span>{idea.saved ? t('idea.savedAgain') : t('idea.save')}</span>
          </button>
        )}
        <button type="button" onClick={() => setShowComments((v) => !v)} aria-expanded={showComments} data-tid="social.idea.comments"
          className={`${btn} inline-flex items-center gap-1.5`}>
          <MessageCircle size={16} aria-hidden="true" />
          <span>{showComments ? t('idea.hideComments') : t('idea.comments')}</span>
          <span>{idea.comments || 0}</span>
        </button>
        {!idea.mine && (
          <button type="button" onClick={() => setReporting(true)} data-tid="social.idea.report" className={`${btn} inline-flex items-center gap-1.5`}>
            <Flag size={16} aria-hidden="true" /><span>{t('idea.report')}</span>
          </button>
        )}
        {idea.mine && !confirmDelete && (
          <button type="button" onClick={() => setConfirmDelete(true)} data-tid="social.idea.delete" className={`${btn} inline-flex items-center gap-1.5`}>
            <Trash2 size={16} aria-hidden="true" /><span>{t('idea.delete')}</span>
          </button>
        )}
      </div>

      {confirmDelete && (
        <div role="alertdialog" aria-label={t('idea.delete')} data-tid="social.idea.deleteConfirm" className="space-y-2 rounded-lg border border-border p-3">
          <p className="text-sm">{t('idea.deleteConfirm')}</p>
          <div className="flex gap-2">
            <button type="button" disabled={busy} onClick={remove} data-tid="social.idea.deleteYes" className={btn}>{t('idea.delete')}</button>
            <button type="button" onClick={() => setConfirmDelete(false)} data-tid="social.idea.deleteNo" className={btn}>{t('actions.cancel')}</button>
          </div>
        </div>
      )}
      {notice && <p role="status" data-tid="social.idea.notice" className="text-sm text-teal-800">{notice}</p>}
      {error && <p role="alert" data-tid="social.idea.error" className="text-sm text-red-600">{error}</p>}

      {showComments && (
        <Comments ideaId={idea.id} ideaMine={!!idea.mine} onCount={(d) => patch({ comments: Math.max(0, (idea.comments || 0) + d) })} />
      )}
      {reporting && <ReportDialog target="idea" id={idea.id} onClose={() => setReporting(false)} />}
    </article>
  )
}
