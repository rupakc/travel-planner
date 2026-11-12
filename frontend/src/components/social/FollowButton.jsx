import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useAuth } from '../../context/AuthContext'
import { follow, unfollow } from '../../services/socialApi'
import { btn, btnPrimary, socialError } from './ui'
import { track } from './track'

/** Follow / request / unfollow. `you` is the profile's {following, pending}; onChange(next you) after the server accepted. */
export default function FollowButton({ handle, you, onChange }) {
  const { t } = useTranslation('social')
  const { token } = useAuth()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const following = !!you?.following
  const pending = !!you?.pending

  const toggle = async () => {
    setBusy(true); setError('')
    try {
      if (following || pending) {
        await unfollow(token, handle)
        track('social_follow', { state: 'none' })
        onChange?.({ following: false, pending: false })
      } else {
        const r = await follow(token, handle)
        const state = r?.state === 'pending' ? 'pending' : 'following'
        track('social_follow', { state })
        onChange?.({ following: state === 'following', pending: state === 'pending' })
      }
    } catch (e) {
      setError(socialError(t, e))
    } finally { setBusy(false) }
  }

  const label = following ? t('profile.following') : pending ? t('profile.requested') : t('profile.follow')
  return (
    <span className="inline-flex flex-col">
      <button type="button" onClick={toggle} disabled={busy} aria-pressed={following || pending}
        data-tid="social.follow" className={following || pending ? btn : btnPrimary}>
        {label}
      </button>
      {error && <span role="alert" data-tid="social.follow.error" className="text-xs text-red-600">{error}</span>}
    </span>
  )
}
