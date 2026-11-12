import { useEffect, useId, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useAuth } from '../../context/AuthContext'
import { checkHandle } from '../../services/socialApi'
import { field } from './ui'

const SHAPE = /^[a-z0-9_]{3,20}$/

/**
 * Handle input with a debounced availability check. `value` is the draft,
 * `current` the saved handle (no check needed for it). Props: onChange, disabled.
 */
export default function HandleField({ value, current = null, onChange, disabled = false, delay = 400 }) {
  const { t } = useTranslation('social')
  const { token } = useAuth()
  const id = useId()
  const [status, setStatus] = useState(null) // null | 'checking' | 'ok' | reason
  const draft = String(value ?? '').trim().toLowerCase()

  useEffect(() => {
    if (!draft || draft === current) { setStatus(null); return undefined }
    if (!SHAPE.test(draft)) { setStatus('invalid'); return undefined }
    let live = true
    setStatus('checking')
    const timer = setTimeout(() => {
      checkHandle(token, draft).then(
        (r) => { if (live) setStatus(r?.available ? 'ok' : (r?.reason || 'invalid')) },
        () => { if (live) setStatus(null) },
      )
    }, delay)
    return () => { live = false; clearTimeout(timer) }
  }, [draft, current, token, delay])

  const bad = status && status !== 'checking' && status !== 'ok'
  return (
    <div>
      <label htmlFor={id} className="block text-sm font-medium">{t('editor.handle')}</label>
      <div className="mt-1 flex items-center gap-1">
        <span aria-hidden="true" className="text-text-muted">@</span>
        <input id={id} type="text" value={value} disabled={disabled} maxLength={20} autoCapitalize="none"
          autoComplete="off" spellCheck={false} data-tid="social.handle.input" aria-invalid={bad || undefined}
          aria-describedby={`${id}-hint`} onChange={(e) => onChange(e.target.value)} className={field} />
      </div>
      <p id={`${id}-hint`} data-tid="social.handle.hint" role="status"
        className={`mt-1 text-xs ${bad ? 'text-red-600' : 'text-text-muted'}`}>
        {status === 'checking' ? t('editor.handleChecking')
          : status === 'ok' ? t('editor.handleOk')
            : bad ? t(`editor.handleReason.${status}`, { defaultValue: t('editor.handleReason.invalid') })
              : t('editor.handleHelp')}
      </p>
    </div>
  )
}
