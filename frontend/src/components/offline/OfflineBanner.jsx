import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useAuth } from '../../context/AuthContext'
import { useJourney } from '../../hooks/useJourney'
import { useOnline } from '../../offline/useOnline'
import { pending, OUTBOX_CHANGED_EVENT } from '../../offline/outbox'

// Slim banner while the device is offline (or /auth/me could not be reached),
// with the number of writes waiting in the outbox. Journey shell only: the
// classic shell renders exactly as before.
export default function OfflineBanner() {
  const { t } = useTranslation('offline')
  const online = useOnline()
  const { user, offline } = useAuth()
  const { enabled } = useJourney()
  const show = enabled && (!online || !!offline)
  const userId = user?.id
  const [count, setCount] = useState(0)

  useEffect(() => {
    if (!show || userId === null || userId === undefined) { setCount(0); return undefined }
    let live = true
    const load = () => { pending(userId).then((n) => { if (live) setCount(n) }, () => {}) }
    load()
    window.addEventListener(OUTBOX_CHANGED_EVENT, load)
    return () => { live = false; window.removeEventListener(OUTBOX_CHANGED_EVENT, load) }
  }, [show, userId])

  if (!show) return null
  return (
    <div
      role="status" data-tid="offline-banner"
      className="flex flex-wrap items-center justify-center gap-x-3 gap-y-1 px-4 py-2 text-sm bg-slate-800 text-white"
    >
      <span data-tid="offline-banner.text">{t('banner.offline')}</span>
      {count > 0 && <span data-tid="offline-banner.pending" className="font-semibold">{t('banner.pending', { count })}</span>}
    </div>
  )
}
