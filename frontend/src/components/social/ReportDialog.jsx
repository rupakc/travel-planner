import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useAuth } from '../../context/AuthContext'
import { sendReport } from '../../services/socialApi'
import SocialDialog from './SocialDialog'
import { btn, btnPrimary, field, socialError } from './ui'
import { track } from './track'

const REASONS = ['spam', 'abuse', 'sexual', 'violence', 'misinformation', 'other']

/** Report an idea, comment or profile. Props: target ('idea'|'comment'|'profile'), id (string|number; the handle for a profile), onClose. */
export default function ReportDialog({ target, id, onClose }) {
  const { t } = useTranslation('social')
  const { token } = useAuth()
  const [reason, setReason] = useState('spam')
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  const [sent, setSent] = useState(false)
  const [error, setError] = useState('')

  const submit = async (e) => {
    e.preventDefault()
    setBusy(true); setError('')
    try {
      const body = { target, id: String(id), reason }
      if (note.trim()) body.note = note.trim().slice(0, 200)
      await sendReport(token, body)
      track('social_report', { target, reason })
      setSent(true)
    } catch (err) {
      setError(socialError(t, err))
    } finally { setBusy(false) }
  }

  return (
    <SocialDialog titleId="report-title" tid="social.report" onClose={onClose}>
      <h2 id="report-title" className="text-base font-semibold">{t('report.title')}</h2>
      {sent ? (
        <>
          <p role="status" data-tid="social.report.sent" className="text-sm">{t('report.sent')}</p>
          <button type="button" onClick={onClose} data-tid="social.report.close" className={btn}>{t('actions.close')}</button>
        </>
      ) : (
        <form onSubmit={submit} className="space-y-3">
          <p className="text-sm text-text-muted">{t('report.intro')}</p>
          <div>
            <label htmlFor="report-reason" className="block text-xs text-text-muted">{t('report.reasonLabel')}</label>
            <select id="report-reason" data-tid="social.report.reason" value={reason}
              onChange={(e) => setReason(e.target.value)} className={field}>
              {REASONS.map((r) => <option key={r} value={r}>{t(`report.reason.${r}`)}</option>)}
            </select>
          </div>
          <div>
            <label htmlFor="report-note" className="block text-xs text-text-muted">{t('report.noteLabel')}</label>
            <textarea id="report-note" data-tid="social.report.note" value={note} maxLength={200} rows={3}
              onChange={(e) => setNote(e.target.value)} className={`${field} py-2`} />
          </div>
          {error && <p role="alert" data-tid="social.report.error" className="text-sm text-red-600">{error}</p>}
          <div className="flex gap-2">
            <button type="submit" disabled={busy} data-tid="social.report.submit" className={btnPrimary}>{t('report.submit')}</button>
            <button type="button" onClick={onClose} data-tid="social.report.cancel" className={btn}>{t('actions.cancel')}</button>
          </div>
        </form>
      )}
    </SocialDialog>
  )
}
