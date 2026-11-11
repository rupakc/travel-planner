import { useEffect, useRef } from 'react'
import { Link } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { useAuth } from '../../context/AuthContext'
import { useAccountSettings } from '../account/SettingsSync'
import { emit } from '../../telemetry/client'
import useGameMe, { levelProgress } from './useGameMe'

const R = 9
const C = 2 * Math.PI * R

// "Lv N" with a ring that fills toward the next level. Renders nothing when
// signed out, when the game is hidden in settings, or when /game/me 404s.
export default function GameNavChip() {
  const { token } = useAuth()
  const { t } = useTranslation('game')
  const { settings } = useAccountSettings()
  const hidden = !!settings?.hide_game
  const { me } = useGameMe(token, !hidden)
  const seen = useRef(false)
  const show = !!me && !hidden && !me.hidden

  useEffect(() => {
    if (show && !seen.current) { seen.current = true; emit('game_view', { surface: 'nav' }) }
  }, [show])

  if (!show) return null
  const pct = levelProgress(me)
  const label = t('chip.label', { level: me.level, xp: me.xp })
  return (
    <Link
      to="/account"
      data-tid="game.navChip"
      className="inline-flex items-center gap-1 rounded-full bg-teal-50 px-1.5 py-0.5 text-xs font-semibold text-teal-700 hover:bg-teal-100 dark:bg-teal-900/40 dark:text-teal-300 dark:hover:bg-teal-900/60"
      aria-label={label}
      title={label}
    >
      <svg width="22" height="22" viewBox="0 0 24 24" aria-hidden="true" className="-rotate-90">
        <circle cx="12" cy="12" r={R} fill="none" strokeWidth="3" className="stroke-teal-200 dark:stroke-teal-900" />
        <circle
          cx="12" cy="12" r={R} fill="none" strokeWidth="3" strokeLinecap="round"
          className="stroke-teal-600 dark:stroke-teal-400"
          strokeDasharray={C} strokeDashoffset={C * (1 - pct)}
          data-tid="game.navChip.ring"
        />
      </svg>
      <span>{t('chip.level', { level: me.level })}</span>
    </Link>
  )
}
