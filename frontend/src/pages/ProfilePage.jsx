import { useCallback, useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { useAuth } from '../context/AuthContext'
import { useAccountSettings } from '../components/account/SettingsSync'
import { getOwnProfile, getProfile, getProfileIdeas } from '../services/socialApi'
import IdeaCard from '../components/social/IdeaCard'
import ProfileEditor from '../components/social/ProfileEditor'
import FollowButton from '../components/social/FollowButton'
import BlockButton from '../components/social/BlockButton'
import ReportDialog from '../components/social/ReportDialog'
import { countryName } from '../components/social/countries'
import { feedPath, profilePath } from '../components/social/paths'
import { btn, card, socialError } from '../components/social/ui'
import { track } from '../components/social/track'

const safeAvatar = (u) => (typeof u === 'string' && (/^\/(?!\/)/.test(u) || /^https:\/\//i.test(u)) ? u : null)

function Badge({ badge }) {
  const { t } = useTranslation(['social', 'game'])
  const id = String(badge?.id ?? '')
  const fallback = id.replace(/_/g, ' ')
  return (
    <li data-tid="social.profile.badge" className="rounded-full bg-surface px-2 py-0.5 text-xs">
      {t(`game:badges.${id}.name`, { defaultValue: fallback })}{badge?.tier ? ` · ${badge.tier}` : ''}
    </li>
  )
}

function ProfileView({ handle, own }) {
  const { t, i18n } = useTranslation('social')
  const { token } = useAuth()
  const [profile, setProfile] = useState(null)
  const [error, setError] = useState(null) // {notFound, text}
  const [ideas, setIdeas] = useState([])
  const [next, setNext] = useState(null)
  const [loadingIdeas, setLoadingIdeas] = useState(false)
  const [reporting, setReporting] = useState(false)
  const lang = i18n.resolvedLanguage || i18n.language || 'en'

  useEffect(() => {
    let live = true
    setProfile(null); setError(null); setIdeas([]); setNext(null)
    getProfile(token, handle).then(
      (p) => { if (live) { setProfile(p); track('social_profile_view') } },
      (e) => { if (live) setError({ notFound: e?.status === 404, text: socialError(t, e) }) },
    )
    return () => { live = false }
  }, [token, handle, t])

  const loadIdeas = useCallback(async (cursor) => {
    setLoadingIdeas(true)
    try {
      const r = await getProfileIdeas(token, handle, cursor)
      setIdeas((cur) => (cursor ? [...cur, ...(r?.ideas || [])] : (r?.ideas || [])))
      setNext(r?.next ?? null)
    } catch { /* a followers-only profile has no ideas to show */ } finally { setLoadingIdeas(false) }
  }, [token, handle])
  useEffect(() => { loadIdeas(null) }, [loadIdeas])

  if (error) {
    return (
      <p role={error.notFound ? 'status' : 'alert'} data-tid="social.profile.error" className={`${card} text-sm`}>
        {error.notFound ? t('profile.notFound') : error.text}
      </p>
    )
  }
  if (!profile) return <p role="status" data-tid="social.profile.loading" className="text-sm text-text-muted">{t('feed.loading')}</p>

  const avatar = safeAvatar(profile.avatar_url)
  const setYou = (patch) => setProfile((p) => {
    // Only an accepted follow counts as a follower (a pending request does not).
    const delta = 'following' in patch ? (patch.following ? 1 : 0) - (p.you?.following ? 1 : 0) : 0
    return {
      ...p,
      followers_count: Math.max(0, (p.followers_count ?? 0) + delta),
      you: { ...(p.you || {}), ...patch },
    }
  })
  const countries = Array.isArray(profile.countries) ? profile.countries : []
  const badges = Array.isArray(profile.badges) ? profile.badges : []
  return (
    <div className="space-y-4">
      <section className={`${card} space-y-3`} data-tid="social.profile" aria-label={t('profile.of', { handle: profile.handle })}>
        <div className="flex items-center gap-3">
          {avatar && <img src={avatar} alt="" width={56} height={56} className="h-14 w-14 rounded-full object-cover" />}
          <div className="min-w-0">
            <h1 className="break-words text-xl font-bold" data-tid="social.profile.handle">@{profile.handle}</h1>
            {profile.you?.follows_you && <p className="text-xs text-text-muted">{t('profile.followsYou')}</p>}
          </div>
        </div>
        {profile.bio && <p className="whitespace-pre-wrap break-words text-sm" data-tid="social.profile.bio">{profile.bio}</p>}
        {profile.home_country && (
          <p className="text-sm" data-tid="social.profile.home">{t('profile.from', { country: countryName(profile.home_country, lang) })}</p>
        )}
        {countries.length > 0 && (
          <p className="text-sm" data-tid="social.profile.countries">
            {t('profile.visited')}: {countries.map((c) => countryName(c, lang)).join(', ')}
          </p>
        )}
        {profile.level != null && <p className="text-sm" data-tid="social.profile.level">{t('profile.level', { level: profile.level })}</p>}
        {badges.length > 0 && <ul className="flex flex-wrap gap-2" aria-label={t('profile.badges')}>{badges.map((b, i) => <Badge key={`${b?.id}-${i}`} badge={b} />)}</ul>}
        <dl className="flex flex-wrap gap-x-5 gap-y-1 text-sm" data-tid="social.profile.counts">
          <div className="flex gap-1"><dt className="text-text-muted">{t('profile.ideas')}</dt><dd>{profile.ideas_count ?? 0}</dd></div>
          <div className="flex gap-1"><dt className="text-text-muted">{t('profile.followers')}</dt><dd>{profile.followers_count ?? 0}</dd></div>
          <div className="flex gap-1"><dt className="text-text-muted">{t('profile.followingLabel')}</dt><dd>{profile.following_count ?? 0}</dd></div>
        </dl>
        {!own && (
          <div className="flex flex-wrap items-start gap-2">
            <FollowButton handle={profile.handle} you={profile.you} onChange={setYou} />
            <button type="button" onClick={() => setReporting(true)} data-tid="social.profile.report" className={btn}>{t('idea.report')}</button>
            <BlockButton handle={profile.handle} onChange={(blocked) => { if (blocked) setError({ notFound: true }) }} />
          </div>
        )}
      </section>

      <section aria-label={t('profile.ideas')} className="space-y-3" data-tid="social.profile.ideas">
        {ideas.map((idea) => (
          <IdeaCard key={idea.id} idea={idea}
            onChange={(u) => setIdeas((cur) => cur.map((x) => (x.id === u.id ? u : x)))}
            onDeleted={(id) => setIdeas((cur) => cur.filter((x) => x.id !== id))} />
        ))}
        {!ideas.length && !loadingIdeas && <p className="text-sm text-text-muted" data-tid="social.profile.noIdeas">{t('profile.noIdeas')}</p>}
        {next && <button type="button" disabled={loadingIdeas} onClick={() => loadIdeas(next)} data-tid="social.profile.more" className={btn}>{t('feed.loadMore')}</button>}
      </section>
      {reporting && <ReportDialog target="profile" id={profile.handle} onClose={() => setReporting(false)} />}
    </div>
  )
}

/** /u/<handle>: a public profile; /u/me: the own-profile editor (creates the profile the first time). */
export default function ProfilePage({ handle }) {
  const { t } = useTranslation('social')
  const { token } = useAuth()
  const navigate = useNavigate()
  const { settings } = useAccountSettings()
  const [own, setOwn] = useState(undefined) // undefined loading, null failed, object
  const [editing, setEditing] = useState(false)
  const wantsEditor = String(handle).toLowerCase() === 'me'

  useEffect(() => {
    let live = true
    getOwnProfile(token).then((p) => { if (live) setOwn(p) }, () => { if (live) setOwn(null) })
    return () => { live = false }
  }, [token])

  const saved = (p) => {
    setOwn(p)
    if (wantsEditor && p?.handle) navigate(profilePath(p.handle), { replace: true })
    else setEditing(false)
  }
  const isOwn = !wantsEditor && own?.handle && own.handle === String(handle).toLowerCase()

  return (
    <main className="mx-auto max-w-2xl space-y-4 px-4 py-6" data-tid="social.profile.page">
      <Link to={feedPath()} data-tid="social.profile.back" className="inline-flex min-h-[44px] items-center text-sm font-medium text-teal-700 hover:underline">
        {t('feed.back')}
      </Link>
      {wantsEditor ? (
        own === undefined ? <p role="status" className="text-sm text-text-muted">{t('feed.loading')}</p>
          : own ? <ProfileEditor profile={own} hideGame={!!settings?.hide_game} onSaved={saved} />
            : <p role="alert" className="text-sm text-red-600">{t('feed.error')}</p>
      ) : (
        <>
          <ProfileView key={handle} handle={handle} own={!!isOwn} />
          {isOwn && (
            <>
              <button type="button" onClick={() => setEditing((v) => !v)} aria-expanded={editing} data-tid="social.profile.edit" className={btn}>
                {editing ? t('actions.close') : t('profile.edit')}
              </button>
              {editing && <ProfileEditor profile={own} hideGame={!!settings?.hide_game} onSaved={saved} />}
            </>
          )}
        </>
      )}
    </main>
  )
}
