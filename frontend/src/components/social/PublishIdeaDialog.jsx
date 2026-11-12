import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { useAuth } from '../../context/AuthContext'
import { localeField } from '../../services/api'
import { getOwnProfile, publishIdea } from '../../services/socialApi'
import SocialDialog from './SocialDialog'
import { btn, btnPrimary, field, socialError } from './ui'
import { feedPath, profilePath } from './paths'
import { track } from './track'

const TITLE_MAX = 80
const CAPTION_MAX = 500

/**
 * Publish a snapshot of a plan or recap to the ideas feed. Strings live in the
 * bundled `socialShare` namespace (this dialog opens from Results, Chat and the recap).
 * Props: kind ('plan'|'recap'), planId, defaultTitle?, onClose.
 */
export default function PublishIdeaDialog({ kind, planId, defaultTitle = '', onClose }) {
  const { t } = useTranslation('socialShare')
  const { token } = useAuth()
  const [own, setOwn] = useState(undefined)
  const [title, setTitle] = useState(defaultTitle)
  const [caption, setCaption] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [result, setResult] = useState(null) // 'published' | 'held'

  useEffect(() => {
    let live = true
    getOwnProfile(token).then((p) => { if (live) setOwn(p) }, () => { if (live) setOwn(null) })
    return () => { live = false }
  }, [token])

  const submit = async (e) => {
    e.preventDefault()
    setBusy(true); setError('')
    try {
      const r = await publishIdea(token, {
        plan_id: planId, kind, title: title.trim(), caption: caption.trim(), ...localeField(),
      })
      track('social_idea_publish', { kind })
      setResult(r?.status === 'held' ? 'held' : 'published')
    } catch (err) {
      setError(socialError(t, err))
    } finally { setBusy(false) }
  }

  let body
  if (result) {
    body = (
      <>
        <p role="status" data-tid="social.publish.done" className="text-sm">{t(result === 'held' ? 'held' : 'done')}</p>
        <div className="flex gap-2">
          <Link to={feedPath()} onClick={onClose} data-tid="social.publish.viewFeed" className={`${btnPrimary} inline-flex items-center`}>{t('viewFeed')}</Link>
          <button type="button" onClick={onClose} data-tid="social.publish.close" className={btn}>{t('close')}</button>
        </div>
      </>
    )
  } else if (own === undefined) {
    body = <p role="status" className="text-sm text-text-muted">{t('loading')}</p>
  } else if (own && !own.handle) {
    body = (
      <>
        <p data-tid="social.publish.needProfile" className="text-sm">{t('needProfile')}</p>
        <Link to={profilePath('me')} onClick={onClose} data-tid="social.publish.createProfile" className={`${btnPrimary} inline-flex items-center`}>{t('createProfile')}</Link>
      </>
    )
  } else if (own && own.visibility === 'private') {
    body = (
      <>
        <p data-tid="social.publish.private" className="text-sm">{t('profilePrivate')}</p>
        <Link to={profilePath(own.handle)} onClick={onClose} data-tid="social.publish.editProfile" className={`${btnPrimary} inline-flex items-center`}>{t('editProfile')}</Link>
      </>
    )
  } else {
    body = (
      <form onSubmit={submit} className="space-y-3">
        <p className="text-sm text-text">{t('intro')}</p>
        <div>
          <label htmlFor="publish-title" className="block text-sm font-medium">{t('titleLabel')}</label>
          <input id="publish-title" type="text" required maxLength={TITLE_MAX} value={title} data-tid="social.publish.title"
            onChange={(e) => setTitle(e.target.value)} className={field} />
          <p className="text-xs text-text-muted">{t('counter', { n: title.length, max: TITLE_MAX })}</p>
        </div>
        <div>
          <label htmlFor="publish-caption" className="block text-sm font-medium">{t('captionLabel')}</label>
          <textarea id="publish-caption" rows={4} maxLength={CAPTION_MAX} value={caption} data-tid="social.publish.caption"
            onChange={(e) => setCaption(e.target.value)} className={`${field} py-2`} />
          <p className="text-xs text-text-muted">{t('counter', { n: caption.length, max: CAPTION_MAX })}</p>
        </div>
        <p className="text-xs text-text-muted">{t('plainNote')}</p>
        {error && <p role="alert" data-tid="social.publish.error" className="text-sm text-red-600">{error}</p>}
        <div className="flex gap-2">
          <button type="submit" disabled={busy || !title.trim()} data-tid="social.publish.submit" className={btnPrimary}>
            {busy ? t('publishing') : t('submit')}
          </button>
          <button type="button" onClick={onClose} data-tid="social.publish.cancel" className={btn}>{t('cancel')}</button>
        </div>
      </form>
    )
  }

  return (
    <SocialDialog titleId="publish-title-h" tid="social.publish" onClose={onClose}>
      <h2 id="publish-title-h" className="text-base font-semibold">{t(kind === 'recap' ? 'titleRecap' : 'title')}</h2>
      {body}
    </SocialDialog>
  )
}
