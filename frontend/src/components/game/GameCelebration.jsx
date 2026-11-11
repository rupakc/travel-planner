import { useCallback, useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Sparkles, Zap } from 'lucide-react'
import { onGameAnnounce } from '../../game/announce'
import { getGameCatalog } from '../../services/gameApi'
import { emit } from '../../telemetry/client'
import { useAccountSettings } from '../account/SettingsSync'
import { badgeIcon, TIER_CLASS } from './icons'

export const DISMISS_MS = 4000
const PIECES = 12
const COLORS = ['#14b8a6', '#f59e0b', '#38bdf8', '#f43f5e', '#a78bfa', '#84cc16']

const CSS = `
.game-confetti{position:absolute;left:50%;top:50%;width:6px;height:10px;border-radius:1px;opacity:0;
  animation:gameConfetti 900ms ease-out forwards;animation-delay:var(--d,0ms)}
@keyframes gameConfetti{
  0%{opacity:1;transform:translate(-50%,-50%) rotate(0)}
  100%{opacity:0;transform:translate(calc(-50% + var(--x)),calc(-50% + var(--y))) rotate(var(--r))}}
.game-pop{animation:gamePop 220ms ease-out both}
@keyframes gamePop{from{opacity:0;transform:translateY(8px) scale(.98)}to{opacity:1;transform:none}}
@media (prefers-reduced-motion: reduce){.game-confetti{display:none}.game-pop{animation:none}}
`

function reducedMotion() {
  try { return !!window.matchMedia?.('(prefers-reduced-motion: reduce)').matches } catch { return false }
}

function Confetti() {
  return (
    <span aria-hidden="true" className="pointer-events-none absolute inset-0 overflow-visible">
      {Array.from({ length: PIECES }, (_, i) => {
        const a = (i / PIECES) * Math.PI * 2
        const d = 46 + (i % 3) * 14
        return (
          <span
            key={i}
            className="game-confetti"
            style={{
              background: COLORS[i % COLORS.length],
              '--x': `${Math.round(Math.cos(a) * d)}px`,
              '--y': `${Math.round(Math.sin(a) * d)}px`,
              '--r': `${(i * 67) % 360}deg`,
              '--d': `${(i % 4) * 40}ms`,
            }}
          />
        )
      })}
    </span>
  )
}

// Toasts for GameDelta announcements: +XP per award, a card for each badge
// (with a short CSS confetti burst, none under reduced motion) and the new
// level. They dismiss themselves after 4 s, sit in a polite live region and
// never take pointer input. Nothing is rendered when the game is hidden.
export default function GameCelebration() {
  const { t } = useTranslation('game')
  const { settings } = useAccountSettings()
  const hidden = !!settings?.hide_game
  const [items, setItems] = useState([])
  const catalog = useRef(null)
  const nextId = useRef(0)
  const timers = useRef(new Set())

  const push = useCallback((item) => {
    const id = nextId.current++
    setItems((cur) => [...cur, { ...item, id }])
    const timer = setTimeout(() => {
      timers.current.delete(timer)
      setItems((cur) => cur.filter((x) => x.id !== id))
    }, DISMISS_MS)
    timers.current.add(timer)
  }, [])

  useEffect(() => {
    if (hidden) return undefined
    const off = onGameAnnounce(async (delta) => {
      for (const a of delta.awards || []) {
        emit('game_award', { rule: a.rule, points: a.points })
        push({ kind: 'award', rule: a.rule, points: a.points })
      }
      if ((delta.badges || []).length && !catalog.current) {
        try { catalog.current = await getGameCatalog() } catch { /* names still come from the locale */ }
      }
      for (const b of delta.badges || []) {
        emit('badge_earned', { badge: b.id })
        const meta = catalog.current?.badges?.find((x) => x.id === b.id)
        push({ kind: 'badge', badge: b.id, tier: meta?.tier, icon: meta?.icon })
      }
      if (delta.level_up) {
        emit('level_up', { level: delta.level_up.to })
        push({ kind: 'level', to: delta.level_up.to })
      }
    })
    return off
  }, [hidden, push])

  useEffect(() => () => {
    for (const timer of timers.current) clearTimeout(timer)
    timers.current.clear()
  }, [])

  if (hidden) return null

  return (
    <div
      role="status"
      aria-live="polite"
      data-tid="game.celebration"
      className="pointer-events-none fixed bottom-4 left-4 z-50 flex max-w-[calc(100vw-2rem)] flex-col gap-2"
    >
      <style>{CSS}</style>
      {items.map((it) => {
        if (it.kind === 'award') {
          return (
            <div key={it.id} data-tid="game.toast.award" className="game-pop pointer-events-none flex items-center gap-2 rounded-xl bg-slate-900 px-3 py-2 text-sm text-white shadow-lg dark:bg-slate-100 dark:text-slate-900">
              <Zap size={14} aria-hidden="true" className="text-amber-400 dark:text-amber-600" />
              {t('toast.xp', { points: it.points, rule: t(`rules.${it.rule}`, { defaultValue: it.rule }) })}
            </div>
          )
        }
        if (it.kind === 'level') {
          return (
            <div key={it.id} data-tid="game.toast.level" className="game-pop pointer-events-none flex items-center gap-2 rounded-xl bg-teal-600 px-3 py-2 text-sm font-semibold text-white shadow-lg dark:bg-teal-400 dark:text-slate-900">
              <Sparkles size={14} aria-hidden="true" />
              {t('toast.level', { to: it.to })}
            </div>
          )
        }
        const Icon = badgeIcon(it.icon)
        return (
          <div key={it.id} data-tid="game.toast.badge" className="game-pop pointer-events-none relative flex items-center gap-3 rounded-xl border border-teal-200 bg-white px-4 py-3 shadow-lg dark:border-teal-800 dark:bg-slate-800">
            {!reducedMotion() && <Confetti />}
            <span className={`rounded-full p-2 ${TIER_CLASS[it.tier] || TIER_CLASS.bronze}`}>
              <Icon size={20} aria-hidden="true" />
            </span>
            <span className="text-sm">
              <span className="block text-xs font-medium uppercase tracking-wide text-teal-700 dark:text-teal-300">{t('toast.badge')}</span>
              <span className="block font-semibold text-slate-800 dark:text-slate-100">{t(`badges.${it.badge}.name`, { defaultValue: it.badge })}</span>
              <span className="block text-xs text-slate-500 dark:text-slate-400">{t(`badges.${it.badge}.desc`, { defaultValue: '' })}</span>
            </span>
          </div>
        )
      })}
    </div>
  )
}
