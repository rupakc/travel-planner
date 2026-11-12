import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useAuth } from '../../context/AuthContext'
import { blockUser, unblockUser } from '../../services/socialApi'
import { btn, socialError } from './ui'
import { track } from './track'

/** Block (with a confirm step) or unblock a handle. onChange(blocked: bool) fires after the server accepted it. */
export default function BlockButton({ handle, blocked = false, onChange }) {
  const { t } = useTranslation('social')
  const { token } = useAuth()
  const [confirm, setConfirm] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const run = async (next) => {
    setBusy(true); setError('')
    try {
      await (next ? blockUser(token, handle) : unblockUser(token, handle))
      track('social_block', { on: next })
      setConfirm(false)
      onChange?.(next)
    } catch (e) {
      setError(socialError(t, e))
    } finally { setBusy(false) }
  }

  if (blocked) {
    return (
      <span className="inline-flex flex-col">
        <button type="button" disabled={busy} onClick={() => run(false)} data-tid="social.unblock" className={btn}>{t('block.unblock')}</button>
        {error && <span role="alert" className="text-xs text-red-600">{error}</span>}
      </span>
    )
  }
  if (!confirm) {
    return <button type="button" onClick={() => setConfirm(true)} data-tid="social.block" className={btn}>{t('block.block')}</button>
  }
  return (
    <div role="alertdialog" aria-label={t('block.block')} data-tid="social.block.confirm" className="space-y-2 rounded-lg border border-border p-3">
      <p className="text-sm">{t('block.confirm', { handle })}</p>
      <div className="flex gap-2">
        <button type="button" disabled={busy} onClick={() => run(true)} data-tid="social.block.yes" className={btn}>{t('block.yes')}</button>
        <button type="button" onClick={() => setConfirm(false)} data-tid="social.block.cancel" className={btn}>{t('actions.cancel')}</button>
      </div>
      {error && <p role="alert" className="text-xs text-red-600">{error}</p>}
    </div>
  )
}
