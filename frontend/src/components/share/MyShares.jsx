import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useAuth } from '../../context/AuthContext'
import { useClientConfig } from '../../hooks/useClientConfig'
import { listShares, revokeShare } from '../../services/api'
import { copyText, pageUrl, sharingEnabled } from '../../utils/share'
import { fmtDate } from '../../i18n/format'

function emit(event, props) {
  import('../../telemetry/client').then((m) => m.emit(event, props)).catch(() => {})
}

const btn = 'min-h-[44px] rounded-lg border border-slate-300 px-3 text-sm text-slate-700 hover:bg-slate-50 disabled:opacity-60'

// The caller's share links with copy and revoke. Hidden when sharing is off
// (config) or the backend has no /shares (404 or any load failure).
export default function MyShares() {
  const { t } = useTranslation('share')
  const { token } = useAuth()
  const { config, loaded } = useClientConfig()
  const on = loaded && sharingEnabled(config)
  const [shares, setShares] = useState(null) // null: loading or hidden
  const [confirming, setConfirming] = useState(null)
  const [note, setNote] = useState(null) // {text, error}

  useEffect(() => {
    if (!on || !token) return undefined
    let live = true
    listShares(token)
      .then((d) => { if (live) setShares(Array.isArray(d?.shares) ? d.shares : []) })
      .catch(() => { if (live) setShares(null) })
    return () => { live = false }
  }, [on, token])

  const copy = useCallback(async (s) => {
    const ok = await copyText(s.url || pageUrl(s.token))
    setNote({ text: t(ok ? 'mine.copied' : 'mine.copyFailed'), error: !ok })
  }, [t])

  const revoke = useCallback(async (s) => {
    try {
      await revokeShare(token, s.token)
      setShares((list) => (list || []).filter((x) => x.token !== s.token))
      setNote({ text: t('mine.revoked'), error: false })
      emit('share_revoke', { kind: ['plan', 'recap', 'savings'].includes(s.kind) ? s.kind : 'plan' })
    } catch {
      setNote({ text: t('mine.error'), error: true })
    }
    setConfirming(null)
  }, [token, t])

  if (!on || !token || shares === null) return null

  return (
    <section data-tid="shares.section" className="bg-white rounded-2xl shadow p-5 mb-4">
      <h2 className="text-lg font-semibold text-slate-800">{t('mine.title')}</h2>
      <p className="text-sm text-slate-500 mb-3">{t('mine.intro')}</p>
      {note && <p role={note.error ? 'alert' : 'status'} className={`mb-3 text-sm ${note.error ? 'text-red-700' : 'text-emerald-700'}`}>{note.text}</p>}
      {shares.length === 0 ? (
        <p data-tid="shares.empty" className="text-sm text-slate-500">{t('mine.empty')}</p>
      ) : (
        <ul className="space-y-3">
          {shares.map((s) => (
            <li key={s.token} data-tid="shares.item" className="rounded-lg border border-slate-200 p-3">
              <p className="text-sm font-medium text-slate-800 break-words">{s.title || t('mine.untitled')}</p>
              <p className="text-xs text-slate-500">
                {t(`mine.kind.${s.kind}`, { defaultValue: t('mine.kind.plan') })}
                {s.created_at ? ` · ${t('mine.created', { date: fmtDate(s.created_at, { month: 'short', day: 'numeric', year: 'numeric' }) })}` : ''}
              </p>
              <div className="mt-2 flex flex-wrap gap-2">
                <button type="button" className={btn} data-tid="shares.copy" onClick={() => copy(s)}>{t('mine.copy')}</button>
                <a className={`${btn} inline-flex items-center`} data-tid="shares.open" href={`/share/${encodeURIComponent(s.token)}`} target="_blank" rel="noopener noreferrer">{t('mine.open')}</a>
                {confirming === s.token ? (
                  <span role="group" aria-label={t('mine.confirm')} className="flex flex-wrap items-center gap-2">
                    <span className="text-sm text-slate-700">{t('mine.confirm')}</span>
                    <button type="button" className={`${btn} border-red-300 text-red-700`} data-tid="shares.revoke.yes" onClick={() => revoke(s)}>{t('mine.yes')}</button>
                    <button type="button" className={btn} data-tid="shares.revoke.no" onClick={() => setConfirming(null)}>{t('mine.no')}</button>
                  </span>
                ) : (
                  <button type="button" className={btn} data-tid="shares.revoke" onClick={() => setConfirming(s.token)}>{t('mine.revoke')}</button>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
