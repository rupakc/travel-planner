import { useCallback, useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { useAuth } from '../context/AuthContext'
import { getFeed, getIdea, getOwnProfile } from '../services/socialApi'
import IdeaCard from '../components/social/IdeaCard'
import { btn, btnPrimary, card, socialError } from '../components/social/ui'
import { feedPath, profilePath } from '../components/social/paths'
import { track } from '../components/social/track'

const SCOPES = ['for_you', 'following', 'new']

function SingleIdea({ id }) {
  const { t } = useTranslation('social')
  const { token } = useAuth()
  const [idea, setIdea] = useState(null)
  const [error, setError] = useState(null)
  const [gone, setGone] = useState(false)

  useEffect(() => {
    let live = true
    setIdea(null); setError(null); setGone(false)
    getIdea(token, id).then(
      (i) => { if (live) { setIdea(i); track('social_idea_open') } },
      (e) => { if (live) setError(e?.status === 404 || e?.status === 403 ? 'gone' : socialError(t, e)) },
    )
    return () => { live = false }
  }, [token, id, t])

  if (gone) return null
  if (error) {
    return (
      <p role="alert" data-tid="social.idea.unavailable" className={`${card} text-sm`}>
        {error === 'gone' ? t('feed.ideaGone') : error}
      </p>
    )
  }
  if (!idea) return <p role="status" className="text-sm text-text-muted">{t('feed.loading')}</p>
  return <IdeaCard idea={idea} expanded link={false} onChange={setIdea} onDeleted={() => setGone(true)} />
}

function FeedList() {
  const { t } = useTranslation('social')
  const { token } = useAuth()
  const [scope, setScope] = useState('for_you')
  const [ideas, setIdeas] = useState([])
  const [next, setNext] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const seq = useRef(0)

  const load = useCallback(async (sc, cursor) => {
    const mine = ++seq.current
    setLoading(true); setError('')
    try {
      const r = await getFeed(token, { scope: sc, cursor })
      if (mine !== seq.current) return
      setIdeas((cur) => (cursor ? [...cur, ...(r?.ideas || [])] : (r?.ideas || [])))
      setNext(r?.next ?? null)
    } catch (e) {
      if (mine === seq.current) setError(socialError(t, e))
    } finally { if (mine === seq.current) setLoading(false) }
  }, [token, t])

  useEffect(() => {
    setIdeas([]); setNext(null)
    load(scope, null)
    track('social_feed_view', { scope })
  }, [scope, load])

  const onKeys = (e) => {
    const i = SCOPES.indexOf(scope)
    const n = e.key === 'ArrowRight' ? i + 1 : e.key === 'ArrowLeft' ? i - 1 : null
    if (n == null) return
    e.preventDefault()
    setScope(SCOPES[(n + SCOPES.length) % SCOPES.length])
  }

  return (
    <>
      <div role="tablist" aria-label={t('feed.scopes')} onKeyDown={onKeys} className="flex gap-1 rounded-xl bg-surface p-1" data-tid="social.feed.scopes">
        {SCOPES.map((s) => (
          <button key={s} type="button" role="tab" aria-selected={scope === s} tabIndex={scope === s ? 0 : -1}
            onClick={() => setScope(s)} data-tid={`social.feed.scope.${s}`}
            className={`min-h-[44px] flex-1 rounded-lg px-2 text-sm font-medium ${scope === s ? 'bg-surface-raised text-teal-700 shadow-sm' : 'text-text-muted hover:text-text'}`}>
            {t(`feed.scope.${s}`)}
          </button>
        ))}
      </div>

      <div className="space-y-3" role="tabpanel" data-tid="social.feed.list" aria-busy={loading}>
        {ideas.map((idea) => (
          <IdeaCard key={idea.id} idea={idea}
            onChange={(u) => setIdeas((cur) => cur.map((x) => (x.id === u.id ? u : x)))}
            onDeleted={(id) => setIdeas((cur) => cur.filter((x) => x.id !== id))} />
        ))}
        {loading && <p role="status" data-tid="social.feed.loading" className="text-sm text-text-muted">{t('feed.loading')}</p>}
        {!loading && !error && !ideas.length && (
          <p data-tid="social.feed.empty" className={`${card} text-sm text-text-muted`}>
            {scope === 'following' ? t('feed.emptyFollowing') : t('feed.empty')}
          </p>
        )}
        {error && (
          <div role="alert" data-tid="social.feed.error" className="space-y-2">
            <p className="text-sm text-red-600">{error}</p>
            <button type="button" onClick={() => load(scope, null)} data-tid="social.feed.retry" className={btn}>{t('feed.retry')}</button>
          </div>
        )}
        {next && !loading && (
          <button type="button" onClick={() => load(scope, next)} data-tid="social.feed.more" className={btn}>{t('feed.loadMore')}</button>
        )}
      </div>
    </>
  )
}

/** /feed (the ideas feed) and /feed/<id> (one idea with its comments). */
export default function FeedPage({ ideaId = null }) {
  const { t } = useTranslation('social')
  const { token } = useAuth()
  const [own, setOwn] = useState(undefined)

  useEffect(() => {
    let live = true
    getOwnProfile(token).then((p) => { if (live) setOwn(p) }, () => { if (live) setOwn(null) })
    return () => { live = false }
  }, [token])

  return (
    <main className="mx-auto max-w-2xl space-y-4 px-4 py-6" data-tid="social.feed.page">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h1 className="text-2xl font-bold text-text">{t('feed.title')}</h1>
        {own?.handle
          ? <Link to={profilePath(own.handle)} data-tid="social.feed.myProfile" className={`${btn} inline-flex items-center`}>{t('feed.myProfile')}</Link>
          : null}
      </div>
      {own && !own.handle && (
        <div className={`${card} space-y-2`} data-tid="social.feed.profilePrompt">
          <p className="text-sm">{t('feed.profilePrompt')}</p>
          <Link to={profilePath('me')} data-tid="social.feed.createProfile" className={`${btnPrimary} inline-flex items-center`}>{t('feed.createProfile')}</Link>
        </div>
      )}
      {ideaId ? (
        <>
          <Link to={feedPath()} data-tid="social.feed.back" className="inline-flex min-h-[44px] items-center text-sm font-medium text-teal-700 hover:underline">{t('feed.back')}</Link>
          <SingleIdea id={ideaId} />
        </>
      ) : <FeedList />}
    </main>
  )
}
