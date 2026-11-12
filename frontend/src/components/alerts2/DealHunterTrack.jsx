import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Trophy } from 'lucide-react'
import { useAuth } from '../../context/AuthContext'
import { useAccountSettings } from '../account/SettingsSync'
import { getGameCatalog } from '../../services/gameApi'
import useGameMe from '../game/useGameMe'

const IS_DEAL = /^(deal_|saver_|bullseye)/

/**
 * The next Deal-hunter badge to earn (the deal_*, saver_* and bullseye ids)
 * with its progress. Renders nothing when the game is hidden in settings
 * (`hide_game`), unavailable, or there is no progress data.
 */
export default function DealHunterTrack() {
  const { t } = useTranslation('alertsHub')
  const { token } = useAuth()
  const { settings } = useAccountSettings()
  const hidden = !!settings?.hide_game
  const { me } = useGameMe(token, !hidden)
  const [catalog, setCatalog] = useState(null)
  const show = !hidden && !!me && !me.hidden

  useEffect(() => {
    if (!show) return undefined
    let live = true
    getGameCatalog().then((c) => { if (live) setCatalog(c) }, () => {})
    return () => { live = false }
  }, [show])

  if (!show) return null
  const mine = Object.fromEntries((me.badges || []).map((b) => [b.id, b]))
  const meta = Object.fromEntries((catalog?.badges || []).map((b) => [b.id, b]))
  const ids = [...new Set([...(catalog?.badges || []).map((b) => b.id), ...Object.keys(mine)])].filter((id) => IS_DEAL.test(id))
  if (!ids.length) return null
  const rows = ids.map((id) => {
    const target = mine[id]?.target ?? meta[id]?.target ?? 1
    return { id, target, progress: mine[id]?.progress ?? 0, earned: !!mine[id]?.earned }
  })
  const open = rows.filter((r) => !r.earned)
  const next = open.sort((a, b) => (b.progress / b.target) - (a.progress / a.target))[0]

  if (!next) {
    return (
      <p data-testid="deal-hunter" data-tid="alerts.deal-hunter"
        className="flex items-center gap-2 text-xs text-slate-600 dark:text-slate-300">
        <Trophy className="h-4 w-4 text-teal-700" aria-hidden="true" />{t('deal.allDone')}
      </p>
    )
  }
  const pct = Math.max(0, Math.min(100, Math.round((100 * next.progress) / next.target)))
  const name = t(`game:badges.${next.id}.name`, { defaultValue: next.id })
  return (
    <div data-testid="deal-hunter" data-tid="alerts.deal-hunter" className="space-y-1">
      <p className="flex items-center gap-2 text-xs font-medium text-slate-700 dark:text-slate-200">
        <Trophy className="h-4 w-4 text-teal-700" aria-hidden="true" />
        <span>{t('deal.title')}: {t('deal.next', { name })}</span>
        <span className="ml-auto tabular-nums text-slate-500 dark:text-slate-400">{t('deal.progress', { progress: next.progress, target: next.target })}</span>
      </p>
      <div role="progressbar" aria-label={t('deal.next', { name })} aria-valuemin={0} aria-valuemax={next.target} aria-valuenow={next.progress}
        className="h-2 overflow-hidden rounded-full bg-slate-200 dark:bg-slate-700">
        <div className="h-full rounded-full bg-teal-700 transition-[width] motion-reduce:transition-none" style={{ width: `${pct}%` }} />
      </div>
    </div>
  )
}
