import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useAuth } from '../../context/AuthContext'
import { useAccountSettings } from '../account/SettingsSync'
import { getGameCatalog } from '../../services/gameApi'
import { emit } from '../../telemetry/client'
import useGameMe, { levelProgress } from './useGameMe'
import { badgeIcon, TIER_CLASS } from './icons'

// Account page card: XP, level, progress bar, badge grid and recent awards.
// `account` is the GET /account payload; null (loading or no account API)
// renders nothing, as does a hidden game or a 404 from /game/me.
export default function GameSection({ account = null }) {
  const { token } = useAuth()
  const { t } = useTranslation('game')
  const { settings } = useAccountSettings()
  const hidden = !!settings?.hide_game
  const on = !!account && !hidden
  const { me } = useGameMe(token, on)
  const [catalog, setCatalog] = useState(null)
  const seen = useRef(false)
  const show = on && !!me && !me.hidden

  useEffect(() => {
    if (!show) return undefined
    let live = true
    getGameCatalog().then((c) => { if (live) setCatalog(c) }, () => {})
    return () => { live = false }
  }, [show])

  useEffect(() => {
    if (show && !seen.current) { seen.current = true; emit('game_view', { surface: 'account' }) }
  }, [show])

  if (!show) return null

  const pct = Math.round(levelProgress(me) * 100)
  const maxed = me.next_level_xp == null
  const mine = Object.fromEntries((me.badges || []).map((b) => [b.id, b]))
  // The catalogue lists every badge; /game/me only has the ones with progress.
  const ids = catalog?.badges?.length ? catalog.badges.map((b) => b.id) : Object.keys(mine)
  const meta = Object.fromEntries((catalog?.badges || []).map((b) => [b.id, b]))
  const badges = ids.map((id) => ({
    id,
    tier: meta[id]?.tier || 'bronze',
    icon: meta[id]?.icon,
    target: mine[id]?.target ?? meta[id]?.target ?? 1,
    progress: mine[id]?.progress ?? 0,
    earned: !!mine[id]?.earned_at,
  }))

  return (
    <section
      className="rounded-2xl bg-white p-6 shadow"
      aria-labelledby="game-title"
      data-tid="game.section"
    >
      <h2 id="game-title" className="mb-4 text-lg font-semibold text-slate-800">
        {t('section.title')}
      </h2>

      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <span className="text-2xl font-bold text-teal-700" data-tid="game.level">
          {t('section.level', { level: me.level })}
        </span>
        <span className="text-sm text-slate-500">
          {t(`levels.${me.level}`, { defaultValue: '' })}
        </span>
        <span className="ml-auto text-sm font-medium text-slate-700" data-tid="game.xp">
          {t('section.xp', { xp: me.xp })}
        </span>
      </div>

      <div
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={pct}
        aria-label={t('section.progressLabel')}
        data-tid="game.progress"
        className="mt-3 h-2.5 overflow-hidden rounded-full bg-slate-200"
      >
        <div className="h-full rounded-full bg-teal-600" style={{ width: `${pct}%` }} />
      </div>
      <p className="mt-1 text-xs text-slate-500">
        {maxed
          ? t('section.maxLevel')
          : t('section.toNext', { remaining: Math.max(0, me.next_level_xp - me.xp), next: me.level + 1 })}
      </p>

      {badges.length > 0 && (
        <>
          <h3 className="mb-2 mt-6 text-sm font-semibold text-slate-700">{t('section.badges')}</h3>
          <ul className="grid grid-cols-2 gap-3 sm:grid-cols-3" data-tid="game.badges">
            {badges.map((b) => {
              const Icon = badgeIcon(b.icon)
              return (
                <li
                  key={b.id}
                  data-tid={`game.badge.${b.id}`}
                  data-earned={b.earned ? 'true' : 'false'}
                  className={`flex items-start gap-2 rounded-xl border p-3 ${
                    b.earned
                      ? 'border-teal-200 bg-teal-50/60'
                      : 'border-slate-200 opacity-60 grayscale'
                  }`}
                >
                  <span className={`mt-0.5 rounded-full p-1.5 ${b.earned ? TIER_CLASS[b.tier] || TIER_CLASS.bronze : 'bg-slate-100 text-slate-400'}`}>
                    <Icon size={16} aria-hidden="true" />
                  </span>
                  <span className="min-w-0 text-sm">
                    <span className="block font-medium text-slate-800">
                      {t(`badges.${b.id}.name`, { defaultValue: b.id })}
                    </span>
                    <span className="block text-xs text-slate-500">
                      {t(`badges.${b.id}.desc`, { defaultValue: '' })}
                    </span>
                    <span className="mt-0.5 block text-xs font-medium text-slate-600">
                      {b.earned ? t('section.earned') : t('section.badgeProgress', { progress: b.progress, target: b.target })}
                    </span>
                  </span>
                </li>
              )
            })}
          </ul>
        </>
      )}

      <h3 className="mb-2 mt-6 text-sm font-semibold text-slate-700">{t('section.recent')}</h3>
      {me.recent?.length ? (
        <ul className="divide-y divide-slate-100 text-sm" data-tid="game.recent">
          {me.recent.map((r, i) => (
            <li key={`${r.rule}-${r.created_at}-${i}`} className="flex justify-between py-1.5 text-slate-700">
              <span>{t(`rules.${r.rule}`, { defaultValue: r.rule })}</span>
              <span className="font-medium text-teal-700">{t('section.points', { points: r.points })}</span>
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-sm text-slate-500">{t('section.recentEmpty')}</p>
      )}
    </section>
  )
}
