import { useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Pencil, Check, X, BadgeCheck, MailWarning } from 'lucide-react'
import { useAuth } from '../../context/AuthContext'
import { updateProfile, uploadAvatar, removeAvatar } from '../../services/accountApi'
import { errorText } from '../../services/apiError'
import { emit } from '../../telemetry/client'
import Avatar from './Avatar'

export const MAX_AVATAR_BYTES = 2 * 1024 * 1024
const AVATAR_TYPES = ['image/jpeg', 'image/png', 'image/webp', 'image/gif']

/**
 * Profile card. The identity comes from /auth/me (`user`), so it renders even
 * when /api/account is unavailable; `account` (null then) gates the editing.
 */
export default function ProfileSection({ account = null, reload }) {
  const { user, token, refreshUser } = useAuth()
  const { t } = useTranslation('profile')
  const fileRef = useRef(null)
  const [editing, setEditing] = useState(false)
  const [name, setName] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  if (!user) return null
  const canEdit = !!account

  const after = async () => {
    await refreshUser?.()
    reload?.()
  }
  const fail = (err) => setError(errorText(t, err))

  const startEdit = () => { setName(user.display_name || user.username || ''); setError(''); setEditing(true) }
  const saveName = async (e) => {
    e?.preventDefault()
    const value = name.trim()
    if (!value) { setError(t('name.required')); return }
    if (value === (user.display_name || user.username)) { setEditing(false); return }
    setBusy(true); setError('')
    try {
      await updateProfile(token, { display_name: value })
      emit('account_action', { action: 'name_change' })
      await after()
      setEditing(false)
    } catch (err) { fail(err) } finally { setBusy(false) }
  }

  const onFile = async (e) => {
    const file = e.target.files?.[0]
    e.target.value = ''
    if (!file) return
    if (!AVATAR_TYPES.includes(file.type)) { setError(t('avatar.badType')); return }
    if (file.size > MAX_AVATAR_BYTES) { setError(t('avatar.tooBig')); return }
    setBusy(true); setError('')
    try {
      await uploadAvatar(token, file)
      emit('account_action', { action: 'avatar_upload' })
      await after()
    } catch (err) { fail(err) } finally { setBusy(false) }
  }
  const onRemove = async () => {
    setBusy(true); setError('')
    try {
      await removeAvatar(token)
      emit('account_action', { action: 'avatar_remove' })
      await after()
    } catch (err) { fail(err) } finally { setBusy(false) }
  }

  const btn = 'text-sm px-3 py-1.5 rounded-lg border border-slate-300 text-slate-700 hover:bg-slate-50 disabled:opacity-50'

  return (
    <section data-tid="profile.section" className="rounded-xl border border-slate-200 bg-white p-5">
      <h2 className="mb-4 text-lg font-semibold text-slate-800">{t('title')}</h2>
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start">
        <div className="flex flex-col items-center gap-2">
          <Avatar user={user} size={80} />
          {canEdit && (
            <div className="flex gap-2">
              <input ref={fileRef} type="file" accept={AVATAR_TYPES.join(',')} className="hidden" onChange={onFile} data-tid="profile.avatarFile" />
              <button type="button" className={btn} disabled={busy} onClick={() => fileRef.current?.click()} data-tid="profile.avatarChange">
                {t('avatar.change')}
              </button>
              {user.avatar_url && (
                <button type="button" className={btn} disabled={busy} onClick={onRemove} data-tid="profile.avatarRemove">
                  {t('avatar.remove')}
                </button>
              )}
            </div>
          )}
        </div>
        <dl className="min-w-0 flex-1 space-y-3 text-sm">
          <div>
            <dt className="text-xs uppercase tracking-wide text-slate-500">{t('name.label')}</dt>
            <dd className="mt-1">
              {editing ? (
                <form onSubmit={saveName} className="flex flex-wrap items-center gap-2">
                  <input
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                    maxLength={50}
                    autoFocus
                    aria-label={t('name.label')}
                    data-tid="profile.nameInput"
                    className="min-w-0 flex-1 rounded-lg border border-slate-300 px-3 py-1.5"
                  />
                  <button type="submit" className={btn} disabled={busy} data-tid="profile.nameSave" aria-label={t('name.save')} title={t('name.save')}><Check size={14} /></button>
                  <button type="button" className={btn} disabled={busy} onClick={() => { setEditing(false); setError('') }} data-tid="profile.nameCancel" aria-label={t('name.cancel')} title={t('name.cancel')}><X size={14} /></button>
                </form>
              ) : (
                <span className="flex items-center gap-2 text-slate-800">
                  <span className="truncate font-medium" data-tid="profile.name">{user.display_name || user.username}</span>
                  {canEdit && (
                    <button type="button" onClick={startEdit} data-tid="profile.nameEdit" aria-label={t('name.edit')} title={t('name.edit')} className="text-slate-400 hover:text-slate-700">
                      <Pencil size={14} />
                    </button>
                  )}
                </span>
              )}
            </dd>
          </div>
          <div>
            <dt className="text-xs uppercase tracking-wide text-slate-500">{t('username.label')}</dt>
            <dd className="mt-1 text-slate-800" data-tid="profile.username">@{user.username}</dd>
          </div>
          {user.email && (
            <div>
              <dt className="text-xs uppercase tracking-wide text-slate-500">{t('email.label')}</dt>
              <dd className="mt-1 flex flex-wrap items-center gap-2 text-slate-800">
                <span className="break-all" data-tid="profile.email">{user.email}</span>
                {user.email_verified ? (
                  <span data-tid="profile.emailVerified" className="inline-flex items-center gap-1 rounded-full bg-emerald-100 px-2 py-0.5 text-xs text-emerald-700">
                    <BadgeCheck size={12} />{t('email.verified')}
                  </span>
                ) : (
                  <span data-tid="profile.emailUnverified" className="inline-flex items-center gap-1 rounded-full bg-amber-100 px-2 py-0.5 text-xs text-amber-700">
                    <MailWarning size={12} />{t('email.unverified')}
                  </span>
                )}
              </dd>
            </div>
          )}
        </dl>
      </div>
      {error && <p role="alert" data-tid="profile.error" className="mt-3 text-sm text-red-600">{error}</p>}
    </section>
  )
}
