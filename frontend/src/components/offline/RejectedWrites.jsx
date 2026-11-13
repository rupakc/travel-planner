import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { listRejected, dismissRejected, OUTBOX_CHANGED_EVENT } from '../../offline/outbox'

// Lists writes the server refused for good (a per-trip cap) while they were
// queued offline, so they are never silently lost. `pathPrefix` scopes it to
// one trip and one kind, e.g. `/trips/12/expenses`. the rows let
// the parent hide the matching "waiting to sync" rows.
export function useRejectedWrites(userId, pathPrefix) {
  const [rows, setRows] = useState([])
  useEffect(() => {
    if (userId === null || userId === undefined || !pathPrefix) { setRows([]); return undefined }
    let live = true
    const load = () => { listRejected(userId, pathPrefix).then((r) => { if (live) setRows(r) }, () => {}) }
    load()
    window.addEventListener(OUTBOX_CHANGED_EVENT, load)
    return () => { live = false; window.removeEventListener(OUTBOX_CHANGED_EVENT, load) }
  }, [userId, pathPrefix])
  return rows
}

export default function RejectedWrites({ userId, rows, summary }) {
  const { t } = useTranslation('offline')
  if (!rows.length) return null
  return (
    <ul role="alert" data-tid="outbox-rejected" className="space-y-2">
      {rows.map((r) => (
        <li key={r.key} className="rounded-lg border border-red-300 bg-red-50 p-3 text-sm text-red-900 dark:border-red-800 dark:bg-red-950 dark:text-red-100">
          <p className="font-medium">{t(`rejected.${r.rejected}`, { defaultValue: t('rejected.generic') })}</p>
          {summary && <p className="mt-1 break-words opacity-90">{summary(r.body)}</p>}
          <button type="button" data-tid="outbox-rejected-dismiss"
            onClick={() => { dismissRejected(userId, r.key) }}
            className="mt-1 min-h-[44px] underline">{t('rejected.dismiss')}</button>
        </li>
      ))}
    </ul>
  )
}
