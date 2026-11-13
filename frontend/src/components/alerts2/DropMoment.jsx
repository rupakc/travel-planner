import { useCallback, useEffect, useRef, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { TrendingDown, X } from 'lucide-react'
import { dropOf, useAlerts } from '../../context/AlertsContext'
import { useAccountSettings } from '../account/SettingsSync'
import { emit } from '../../telemetry/client'
import { fmtNumber } from '../../i18n/format'
import SavingsShareCard from './SavingsShareCard'

const COUNT_MS = 900
const PIECES = 14
const COLORS = ['#14b8a6', '#f59e0b', '#38bdf8', '#f43f5e', '#a78bfa', '#84cc16']
const KINDS = ['flight', 'hotel', 'activity', 'trip']
const FOCUSABLE = 'a[href],button:not([disabled]),[tabindex]:not([tabindex="-1"])'

const CSS = `
.drop-card{animation:dropSlide 320ms cubic-bezier(.2,.8,.2,1) both}
@keyframes dropSlide{from{opacity:0;transform:translateY(28px)}to{opacity:1;transform:none}}
.drop-fall{animation:dropFall 900ms ease-in both}
@keyframes dropFall{from{opacity:0;transform:translateY(-14px)}to{opacity:1;transform:none}}
.drop-confetti{position:absolute;left:50%;top:40%;width:6px;height:10px;border-radius:1px;opacity:0;
  animation:dropConfetti 1100ms ease-out forwards;animation-delay:var(--d,0ms)}
@keyframes dropConfetti{
  0%{opacity:1;transform:translate(-50%,-50%) rotate(0)}
  100%{opacity:0;transform:translate(calc(-50% + var(--x)),calc(-50% + var(--y))) rotate(var(--r))}}
@media (prefers-reduced-motion: reduce){.drop-card,.drop-fall{animation:none}.drop-confetti{display:none}}
`

function reducedMotion() {
  try { return !!window.matchMedia?.('(prefers-reduced-motion: reduce)').matches } catch { return false }
}

const money = (amount, currency) => {
  const n = Number(amount)
  try {
    return fmtNumber(n, {
      style: 'currency', currency, minimumFractionDigits: Number.isInteger(n) ? 0 : 2, maximumFractionDigits: 2,
    })
  } catch { return fmtNumber(n) }
}

// "−12 %" style share from the server's whole-number pct
const percent = (pct) => fmtNumber(Math.abs(Number(pct)) / 100, { style: 'percent', maximumFractionDigits: 0 })

const safeUrl = (u) => {
  try { return ['http:', 'https:'].includes(new URL(u).protocol) ? u : null } catch { return null }
}

/** Counts 0 -> 1 over COUNT_MS (rAF); reduced motion returns 1 at once. */
function useProgress(active, key) {
  const [p, setP] = useState(() => (reducedMotion() ? 1 : 0))
  useEffect(() => {
    if (!active) return undefined
    if (reducedMotion()) { setP(1); return undefined }
    setP(0)
    let raf = 0
    const start = performance.now()
    const step = (now) => {
      const x = Math.min(1, (now - start) / COUNT_MS)
      setP(1 - (1 - x) ** 3)
      if (x < 1) raf = requestAnimationFrame(step)
    }
    raf = requestAnimationFrame(step)
    return () => cancelAnimationFrame(raf)
  }, [active, key])
  return p
}

function Confetti() {
  return (
    <span aria-hidden="true" data-tid="dropMoment.confetti" className="pointer-events-none absolute inset-0 overflow-visible">
      {Array.from({ length: PIECES }, (_, i) => {
        const a = (i / PIECES) * Math.PI * 2
        const d = 70 + (i % 3) * 22
        return (
          <span key={i} className="drop-confetti" style={{
            background: COLORS[i % COLORS.length],
            '--x': `${Math.round(Math.cos(a) * d)}px`, '--y': `${Math.round(Math.sin(a) * d)}px`,
            '--r': `${(i * 67) % 360}deg`, '--d': `${(i % 4) * 50}ms`,
          }} />
        )
      })}
    </span>
  )
}

function Card({ note, via, onClose }) {
  const { t } = useTranslation('dropMoment')
  const { t: tg } = useTranslation('game')
  const { settings } = useAccountSettings()
  const navigate = useNavigate()
  const drop = dropOf(note)
  const data = note.data || {}
  const kind = KINDS.includes(data.watch_kind) ? data.watch_kind : 'flight'
  const currency = drop.currency || 'USD'
  const hit = drop.target_hit === true
  const awards = Array.isArray(data.game?.awards) ? data.game.awards : []
  const xp = awards.reduce((sum, a) => sum + (Number(a?.points) || 0), 0)
  const showXp = xp > 0 && !settings?.hide_game
  const badges = Array.isArray(data.game?.badges) ? data.game.badges.filter((b) => b?.id) : []
  const showBadges = badges.length > 0 && !settings?.hide_game
  const book = safeUrl(data.links?.book)
  const watchKey = data.watch_id != null ? `${kind}:${data.watch_id}` : null
  const progress = useProgress(true, note.id)
  const [sharing, setSharing] = useState(false)
  const ref = useRef(null)
  const closeRef = useRef(null)

  const amount = Number(drop.amount)
  const shownAmount = Math.round(amount * progress * 100) / 100
  const shownPrice = Number(drop.from) + (Number(drop.to) - Number(drop.from)) * progress

  // Focus the card on open, trap Tab inside, Escape closes (the opener restores focus)
  useEffect(() => { closeRef.current?.focus() }, [])
  const onKeyDown = (e) => {
    if (e.key === 'Escape') { e.stopPropagation(); onClose(); return }
    if (e.key !== 'Tab') return
    const els = [...(ref.current?.querySelectorAll(FOCUSABLE) || [])]
    if (!els.length) return
    const first = els[0]
    const last = els[els.length - 1]
    if (e.shiftKey && (document.activeElement === first || !ref.current.contains(document.activeElement))) {
      e.preventDefault(); last.focus()
    } else if (!e.shiftKey && document.activeElement === last) {
      e.preventDefault(); first.focus()
    }
  }

  useEffect(() => {
    emit('alert_drop_seen', { kind, target_hit: hit, via })
  }, [note.id])

  const btn = 'inline-flex min-h-[44px] items-center justify-center rounded-full px-5 text-sm font-semibold focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-teal-600'
  const primary = `${btn} bg-teal-700 hover:bg-teal-800 text-white`
  const secondary = `${btn} border border-slate-300 bg-white text-slate-800 hover:bg-slate-50`

  const savings = {
    total_usd: currency === 'USD' ? amount : 0,
    by_currency: currency === 'USD' ? {} : { [currency]: amount },
    drops_caught: 1, targets_hit: hit ? 1 : 0, watches_active: 1, best: null,
    milestones: [], next_milestone: null, progress_pct: 0, since: null,
  }

  return (
    <div className="fixed inset-0 z-[80] flex items-end justify-center bg-slate-900/50 p-4 sm:items-center"
      onMouseDown={(e) => { if (e.target === e.currentTarget) onClose() }}>
      <style>{CSS}</style>
      <div ref={ref} role="dialog" aria-modal="true" aria-labelledby="drop-moment-title" data-tid="dropMoment.card"
        onKeyDown={onKeyDown}
        className="drop-card relative w-full max-w-sm rounded-2xl bg-white p-6 text-center shadow-2xl">
        {hit && <Confetti />}
        <button ref={closeRef} type="button" data-tid="dropMoment.close" onClick={onClose} aria-label={t('close')}
          className="absolute right-2 top-2 inline-flex h-11 w-11 items-center justify-center rounded-full text-slate-500 hover:bg-slate-100 focus-visible:outline focus-visible:outline-2 focus-visible:outline-teal-600">
          <X size={18} aria-hidden="true" />
        </button>
        <span className="drop-fall mx-auto flex h-12 w-12 items-center justify-center rounded-full bg-teal-100 text-teal-700">
          <TrendingDown size={24} aria-hidden="true" />
        </span>
        <h2 id="drop-moment-title" className="mt-3 text-lg font-bold text-slate-900">
          {hit ? t('titleTarget') : t('title')}
        </h2>
        {data.title && <p className="mt-0.5 line-clamp-2 text-sm text-slate-500">{data.title}</p>}
        <p data-tid="dropMoment.amount" className="mt-4 text-4xl font-extrabold tabular-nums text-teal-700">
          <span className="sr-only">{t('caught', { amount: money(amount, currency), percent: percent(drop.pct) })}</span>
          <span aria-hidden="true">{'−'}{money(shownAmount, currency)}</span>
          <span aria-hidden="true" className="ml-2 text-lg font-semibold">({'−'}{percent(drop.pct)})</span>
        </p>
        <p className="mt-1 text-sm tabular-nums text-slate-600">
          <s className="text-slate-400">{money(drop.from, currency)}</s>
          <span aria-hidden="true"> {'→'} </span>
          <span className="sr-only">{t('nowPrice')}</span>
          <strong data-tid="dropMoment.price">{money(shownPrice, currency)}</strong>
        </p>
        {showXp && (
          <p data-tid="dropMoment.xp" className="mt-3 inline-block rounded-full bg-amber-100 px-3 py-1 text-sm font-semibold text-amber-800">
            {t('xp', { xp })}
          </p>
        )}
        {showBadges && badges.map((b) => (
          <p key={b.id} data-tid="dropMoment.badge" className="mt-2 inline-block rounded-full bg-teal-100 px-3 py-1 text-sm font-semibold text-teal-800">
            {t('badge', { name: tg(`badges.${b.id}.name`, { defaultValue: b.id }) })}
          </p>
        ))}
        <p className="mt-3 text-xs text-slate-500">{t('note')}</p>
        <div className="mt-5 flex flex-wrap justify-center gap-2">
          {watchKey && (
            <button type="button" data-tid="dropMoment.story" className={primary}
              onClick={() => { navigate(`/alerts?watch=${watchKey}`); onClose() }}>{t('story')}</button>
          )}
          {book && (
            <a data-tid="dropMoment.book" href={book} target="_blank" rel="noopener noreferrer" className={secondary}>{t('book')}</a>
          )}
          <button type="button" data-tid="dropMoment.share" className={secondary} onClick={() => setSharing(true)}>{t('share')}</button>
          <button type="button" data-tid="dropMoment.dismiss" className={secondary} onClick={onClose}>{t('close')}</button>
        </div>
        {sharing && <SavingsShareCard savings={savings} onClose={() => setSharing(false)} />}
      </div>
    </div>
  )
}

/** The animated "caught a drop" card: the newest unread drop not yet shown on this device, or
 * the one a push deep link names (`/alerts?drop=<notification_id>`). */
export default function DropMoment() {
  const { latestDrop, markDropShown, findDrop } = useAlerts()
  const location = useLocation()
  const navigate = useNavigate()
  const [linked, setLinked] = useState(null)
  const [open, setOpen] = useState(null)   // { note, via }
  const opener = useRef(null)
  const autoShown = useRef(false)   // one automatic card per page load

  const linkId = Number(new URLSearchParams(location.search).get('drop')) || null
  const seenLink = useRef(null)

  useEffect(() => {
    if (!linkId || seenLink.current === linkId) return undefined
    seenLink.current = linkId
    let active = true
    findDrop(linkId).then((n) => {
      if (!active) return
      if (n) { setLinked(n); return }
      const params = new URLSearchParams(location.search)
      params.delete('drop')   // unknown or expired id: drop the param, nothing opens
      const qs = params.toString()
      navigate({ pathname: location.pathname, search: qs ? `?${qs}` : '' }, { replace: true })
    })
    return () => { active = false }
  }, [linkId, findDrop])

  const show = useCallback((note, via) => {
    autoShown.current = true   // any card counts: closing it never opens the next one
    opener.current = document.activeElement
    setOpen({ note, via })
    markDropShown(note.id)
  }, [markDropShown])

  // A deep link wins over the automatic card
  useEffect(() => {
    if (open || !linked) return
    show(linked, 'push')
    setLinked(null)
    const params = new URLSearchParams(location.search)
    params.delete('drop')
    const qs = params.toString()
    navigate({ pathname: location.pathname, search: qs ? `?${qs}` : '' }, { replace: true })
  }, [linked, open, show, navigate, location.pathname, location.search])

  useEffect(() => {
    if (!open && !linked && !linkId && latestDrop && !autoShown.current) {
      show(latestDrop, 'in_app')
    }
  }, [open, linked, linkId, latestDrop, show])

  const close = useCallback(() => {
    setOpen(null)
    const el = opener.current
    opener.current = null
    if (el && typeof el.focus === 'function' && document.contains(el)) el.focus()
  }, [])

  if (!open) return null
  return <Card key={open.note.id} note={open.note} via={open.via} onClose={close} />
}
