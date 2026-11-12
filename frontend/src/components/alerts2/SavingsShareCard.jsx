import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { fmtCurrency } from '../../i18n/format'
import { drawSavingsCard, savingsCardLines, shareSavings, renderSavingsBlob, CARD_SIZE } from '../../utils/savingsCard'

function emitShare(target) {
  import('../../telemetry/client').then((m) => m.emit('alert_savings_share', { target })).catch(() => {})
}

const isDark = () => {
  try { return !!window.matchMedia?.('(prefers-color-scheme: dark)').matches } catch { return false }
}

/**
 * Preview and share dialog. `savings` may be the full /alerts/summary object or
 * a minimal one ({ total_usd, by_currency, drops_caught }), e.g. one drop.
 * Escape closes only this dialog (the event never reaches a parent dialog).
 */
export default function SavingsShareCard({ savings, onClose }) {
  const { t } = useTranslation('savings')
  const canvasRef = useRef(null)
  const dialogRef = useRef(null)
  const [status, setStatus] = useState(null)
  const [busy, setBusy] = useState(false)
  const lines = savingsCardLines(savings, t, fmtCurrency)
  const theme = isDark() ? 'dark' : 'light'

  useEffect(() => {
    const ctx = canvasRef.current?.getContext?.('2d')
    if (ctx) drawSavingsCard(ctx, savings, lines, theme)
  }, [savings, theme])

  useEffect(() => {
    dialogRef.current?.focus()
    const onKey = (e) => {
      if (e.key !== 'Escape') return
      e.stopPropagation()
      e.preventDefault()
      onClose?.()
    }
    window.addEventListener('keydown', onKey, true)
    return () => window.removeEventListener('keydown', onKey, true)
  }, [onClose])

  const share = async () => {
    setBusy(true)
    setStatus(null)
    try {
      const blob = await renderSavingsBlob(savings, lines, theme)
      const target = await shareSavings(blob, lines.headline)
      if (target) { emitShare(target); setStatus(target) }
    } catch { setStatus('error') } finally { setBusy(false) }
  }

  return (
    <div className="fixed inset-0 z-[80] flex items-center justify-center bg-black/50 p-4" data-tid="savings-share-backdrop"
      onClick={(e) => { if (e.target === e.currentTarget) onClose?.() }}>
      <div ref={dialogRef} role="dialog" aria-modal="true" aria-label={t('shareTitle')} tabIndex={-1}
        data-tid="savings-share-dialog"
        className="w-full max-w-sm space-y-3 rounded-2xl bg-white p-4 shadow-xl outline-none">
        <h2 className="text-base font-semibold text-slate-900">{t('shareTitle')}</h2>
        <canvas ref={canvasRef} width={CARD_SIZE} height={CARD_SIZE} role="img" aria-label={t('preview')}
          className="h-auto w-full rounded-xl border border-slate-200" />
        <p className="text-sm text-slate-700">{lines.headline}</p>
        {status && (
          <p role="status" className="text-xs text-slate-600" data-testid="share-status">{t(`status.${status}`)}</p>
        )}
        <div className="flex gap-2">
          <button type="button" data-tid="savings-share-go" onClick={share} disabled={busy}
            className="min-h-[44px] flex-1 rounded-lg bg-teal-700 px-4 text-sm font-semibold text-white hover:bg-teal-800 disabled:opacity-60">
            {busy ? t('working') : t('share')}
          </button>
          <button type="button" data-tid="savings-share-close" onClick={onClose}
            className="min-h-[44px] rounded-lg border border-slate-300 px-4 text-sm text-slate-700">
            {t('close')}
          </button>
        </div>
      </div>
    </div>
  )
}
