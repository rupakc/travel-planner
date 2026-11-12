import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Bell, BellOff } from 'lucide-react'
import { primaryBtn, secondaryBtn } from './QuizStep'

/** True when this browser can ask for notification permission at all. */
export function notificationsSupported() {
  try {
    return typeof window !== 'undefined' && 'Notification' in window
      && typeof window.Notification?.requestPermission === 'function'
  } catch {
    return false
  }
}

const currentPermission = () => {
  try { return window.Notification.permission } catch { return 'default' }
}

/**
 * Step 4: the contextual ask. The browser prompt appears only after "Allow
 * notifications"; a blocked permission is explained instead of asked.
 */
export default function NotificationsStep({ onBack, onDone }) {
  const { t } = useTranslation('onboarding')
  const [permission] = useState(currentPermission)
  const [asking, setAsking] = useState(false)

  const allow = async () => {
    setAsking(true)
    try { await window.Notification.requestPermission() } catch { /* dismissed or unsupported */ }
    setAsking(false)
    onDone('next')
  }

  return (
    <section data-tid="onboarding.step.notifications" aria-labelledby="onboarding-notif-title" className="space-y-5">
      <div className="flex items-start gap-4">
        <span aria-hidden="true" className="shrink-0 w-12 h-12 rounded-2xl bg-teal-100 text-teal-800 flex items-center justify-center">
          {permission === 'denied' ? <BellOff size={24} /> : <Bell size={24} />}
        </span>
        <div>
          <h2 id="onboarding-notif-title" className="font-display text-xl sm:text-2xl font-semibold text-gray-900">
            {t('steps.notifications.title')}
          </h2>
          <p className="text-sm text-gray-600 mt-1">{t('steps.notifications.body')}</p>
        </div>
      </div>
      {permission === 'denied' && (
        <div data-tid="onboarding.notifications.blocked" role="status" className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3">
          <p className="text-sm font-semibold text-amber-900">{t('web.notificationsBlocked')}</p>
          <p className="text-xs text-amber-900 mt-0.5">{t('web.notificationsBlockedBody')}</p>
        </div>
      )}
      {permission === 'granted' && (
        <p data-tid="onboarding.notifications.on" role="status" className="text-sm font-medium text-teal-800">
          {t('web.notificationsOn')}
        </p>
      )}
      <div className="flex flex-col-reverse sm:flex-row sm:items-center sm:justify-between gap-2 pt-1">
        <button type="button" data-tid="onboarding.back" onClick={onBack} className={secondaryBtn}>{t('nav.back')}</button>
        {permission === 'default' ? (
          <div className="flex flex-col-reverse sm:flex-row sm:items-center gap-2">
            <button type="button" data-tid="onboarding.notifications.later" onClick={() => onDone('skip')} className={secondaryBtn}>
              {t('web.notNow')}
            </button>
            <button type="button" data-tid="onboarding.notifications.allow" onClick={allow} disabled={asking} className={primaryBtn}>
              {t('web.allowNotifications')}
            </button>
          </div>
        ) : (
          <button type="button" data-tid="onboarding.next" onClick={() => onDone('next')} className={primaryBtn}>
            {t('web.continue')}
          </button>
        )}
      </div>
    </section>
  )
}
