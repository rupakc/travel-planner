import { useCallback, useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useAuth } from '../../context/AuthContext'
import {
  acceptRequest, declineRequest, listBlocks, listFollowRequests, putProfile, unblockUser,
} from '../../services/socialApi'
import HandleField from './HandleField'
import Handle from './Handle'
import { COUNTRY_CODES, countryName } from './countries'
import { btn, btnPrimary, card, field, socialError } from './ui'
import { track } from './track'

const VISIBILITY = ['private', 'followers', 'public']
const FLAGS = ['show_avatar', 'show_home_country', 'show_countries', 'show_level', 'show_badges', 'leaderboard_opt_in']
const GAME_FLAGS = ['show_level', 'show_badges', 'leaderboard_opt_in']
const BIO_MAX = 160

function PeopleList({ title, tid, users, actions }) {
  if (!users.length) return null
  return (
    <section className={`${card} space-y-2`} data-tid={tid} aria-label={title}>
      <h3 className="text-sm font-semibold">{title}</h3>
      <ul className="space-y-2">
        {users.map((u) => (
          <li key={u.handle} className="flex flex-wrap items-center justify-between gap-2">
            <Handle handle={u.handle} tid={`${tid}.handle`} />
            <span className="flex gap-2">{actions(u)}</span>
          </li>
        ))}
      </ul>
    </section>
  )
}

/**
 * The own-profile editor. `profile` is GET /social/profile (handle null = no profile yet).
 * Props: profile, hideGame (hides the game-only switches), onSaved(profile).
 */
export default function ProfileEditor({ profile, hideGame = false, onSaved }) {
  const { t, i18n } = useTranslation('social')
  const { token } = useAuth()
  const [draft, setDraft] = useState(() => ({
    handle: profile.handle || '',
    visibility: profile.visibility || 'private',
    bio: profile.bio || '',
    home_country: profile.home_country || '',
    ...Object.fromEntries(FLAGS.map((f) => [f, !!profile[f]])),
  }))
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [saved, setSaved] = useState(false)
  const [requests, setRequests] = useState([])
  const [blocks, setBlocks] = useState([])
  const set = (patch) => { setDraft((d) => ({ ...d, ...patch })); setSaved(false) }
  const lang = i18n.resolvedLanguage || i18n.language || 'en'
  const countries = useMemo(
    () => COUNTRY_CODES.map((c) => [c, countryName(c, lang)]).sort((a, b) => a[1].localeCompare(b[1], lang)),
    [lang],
  )

  const loadLists = useCallback(() => {
    if (!profile.handle) return
    listFollowRequests(token).then((r) => setRequests(r?.requests || []), () => setRequests([]))
    listBlocks(token).then((r) => setBlocks(r?.users || []), () => setBlocks([]))
  }, [token, profile.handle])
  useEffect(() => { loadLists() }, [loadLists])

  const submit = async (e) => {
    e.preventDefault()
    setBusy(true); setError(''); setSaved(false)
    const body = {
      visibility: draft.visibility,
      bio: draft.bio,
      home_country: draft.home_country || null,
      ...Object.fromEntries(FLAGS.map((f) => [f, !!draft[f]])),
    }
    const handle = draft.handle.trim().toLowerCase()
    if (handle && handle !== profile.handle) body.handle = handle
    try {
      const p = await putProfile(token, body)
      track('social_profile_save', { visibility: p?.visibility || draft.visibility })
      setSaved(true)
      onSaved?.(p)
    } catch (err) {
      setError(socialError(t, err))
    } finally { setBusy(false) }
  }

  const answer = async (u, accept) => {
    try {
      await (accept ? acceptRequest(token, u.handle) : declineRequest(token, u.handle))
      setRequests((cur) => cur.filter((x) => x.handle !== u.handle))
    } catch (err) { setError(socialError(t, err)) }
  }
  const unblock = async (u) => {
    try {
      await unblockUser(token, u.handle)
      track('social_block', { on: false })
      setBlocks((cur) => cur.filter((x) => x.handle !== u.handle))
    } catch (err) { setError(socialError(t, err)) }
  }

  const flagLabel = (f) => t(`editor.flag.${f}`)
  return (
    <div className="space-y-4" data-tid="social.editor">
      <form onSubmit={submit} className={`${card} space-y-4`}>
        <h2 className="text-lg font-semibold">{profile.handle ? t('editor.title') : t('editor.createTitle')}</h2>
        <p className="text-sm text-text-muted">{t('editor.intro')}</p>
        <HandleField value={draft.handle} current={profile.handle} onChange={(v) => set({ handle: v })} />
        <div>
          <label htmlFor="editor-visibility" className="block text-sm font-medium">{t('editor.visibility')}</label>
          <select id="editor-visibility" data-tid="social.editor.visibility" value={draft.visibility}
            onChange={(e) => set({ visibility: e.target.value })} className={`${field} mt-1`}>
            {VISIBILITY.map((v) => <option key={v} value={v}>{t(`editor.visibilityOption.${v}`)}</option>)}
          </select>
          <p className="mt-1 text-xs text-text-muted">{t(`editor.visibilityNote.${draft.visibility}`)}</p>
        </div>
        <div>
          <label htmlFor="editor-bio" className="block text-sm font-medium">{t('editor.bio')}</label>
          <textarea id="editor-bio" data-tid="social.editor.bio" value={draft.bio} maxLength={BIO_MAX} rows={3}
            onChange={(e) => set({ bio: e.target.value })} className={`${field} mt-1 py-2`} />
          <p className="text-xs text-text-muted">{t('editor.counter', { n: draft.bio.length, max: BIO_MAX })}</p>
        </div>
        <div>
          <label htmlFor="editor-country" className="block text-sm font-medium">{t('editor.homeCountry')}</label>
          <select id="editor-country" data-tid="social.editor.country" value={draft.home_country}
            onChange={(e) => set({ home_country: e.target.value })} className={`${field} mt-1`}>
            <option value="">{t('editor.none')}</option>
            {countries.map(([c, n]) => <option key={c} value={c}>{n}</option>)}
          </select>
        </div>
        <fieldset className="space-y-1">
          <legend className="text-sm font-medium">{t('editor.showLegend')}</legend>
          <p className="text-xs text-text-muted">{t('editor.showNote')}</p>
          {FLAGS.filter((f) => !(hideGame && GAME_FLAGS.includes(f))).map((f) => (
            <label key={f} className="flex min-h-[44px] items-center gap-3 text-sm">
              <input type="checkbox" checked={!!draft[f]} data-tid={`social.editor.${f}`} className="h-5 w-5 shrink-0 rounded border-border text-teal-700"
                onChange={(e) => set({ [f]: e.target.checked })} />
              {flagLabel(f)}
            </label>
          ))}
        </fieldset>
        {error && <p role="alert" data-tid="social.editor.error" className="text-sm text-red-600">{error}</p>}
        {saved && <p role="status" data-tid="social.editor.saved" className="text-sm text-teal-800">{t('editor.saved')}</p>}
        <button type="submit" disabled={busy} data-tid="social.editor.save" className={btnPrimary}>
          {busy ? t('editor.saving') : t('editor.save')}
        </button>
      </form>

      <PeopleList title={t('editor.requests')} tid="social.requests" users={requests} actions={(u) => (
        <>
          <button type="button" onClick={() => answer(u, true)} data-tid="social.requests.accept" className={btn}>{t('editor.accept')}</button>
          <button type="button" onClick={() => answer(u, false)} data-tid="social.requests.decline" className={btn}>{t('editor.decline')}</button>
        </>
      )} />
      <PeopleList title={t('editor.blocked')} tid="social.blocks" users={blocks} actions={(u) => (
        <button type="button" onClick={() => unblock(u)} data-tid="social.blocks.unblock" className={btn}>{t('block.unblock')}</button>
      )} />
    </div>
  )
}
