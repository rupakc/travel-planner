import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useAuth } from '../../context/AuthContext'
import { useJourney } from '../../hooks/useJourney'
import { getOfflinePack } from '../../services/tripsApi'
import { savePack, deletePack } from '../../offline/packStore'
import { ensureServiceWorker, precacheShell } from '../../offline/registerSW'
import { useOfflinePack } from '../../offline/useOfflinePack'
import { useOnline } from '../../offline/useOnline'
import { emit } from '../../telemetry/client'
import { fmtDate } from '../../i18n/format'
import EmergencyNumbers from './EmergencyNumbers'
import PhraseList from './PhraseList'
import AddressCard from './AddressCard'
import CurrencyConverter from './CurrencyConverter'

const btn = 'min-h-[44px] px-4 rounded-lg text-sm font-medium disabled:opacity-50'
const sizeKb = (pack) => Math.max(1, Math.round(JSON.stringify(pack).length / 1024))
const safe = (props) => { try { emit('offline_pack', props) } catch { /* telemetry never breaks the UI */ } }

export default function OfflinePack({ trip, token }) {
  const { t } = useTranslation('offlinePack')
  const { enabled, offlinePack } = useJourney()
  const { user } = useAuth()
  const online = useOnline()
  const rawId = user?.id ?? user?.username
  const userId = rawId == null || rawId === '' ? null : String(rawId)
  const stored = useOfflinePack(userId, trip?.id)
  const [local, setLocal] = useState(null) // {pack, savedAt, kb, worker} after a save here
  const [removed, setRemoved] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  const pack = removed ? null : (local?.pack ?? stored.pack)
  const savedAt = removed ? null : (local?.savedAt ?? stored.savedAt ?? stored.pack?.saved_at)
  const kb = local?.kb ?? (pack ? sizeKb(pack) : 0)

  const save = useCallback(async (action) => {
    if (!offlinePack) return
    setBusy(true)
    setError(null)
    let result = 'error'
    let savedKb = 0
    try {
      if (!userId) throw new Error('no_user')
      const fresh = await getOfflinePack(token, trip.id)
      await savePack(userId, fresh)
      savedKb = sizeKb(fresh)
      let worker = false
      try {
        const reg = await ensureServiceWorker()
        if (reg) {
          const shell = await precacheShell()
          worker = !!shell?.ok
        }
        await navigator.storage?.persist?.()
      } catch { /* the data is saved; only the offline shell failed */ }
      setLocal({ pack: fresh, savedAt: new Date().toISOString(), kb: savedKb, worker })
      setRemoved(false)
      result = worker ? 'ok' : 'unsupported'
    } catch (e) {
      result = e?.name === 'QuotaExceededError' ? 'quota' : 'error'
      setError(result)
    } finally {
      setBusy(false)
      safe({ action, result, kb: savedKb })
    }
  }, [token, trip?.id, userId, offlinePack])

  const remove = async () => {
    setBusy(true)
    try {
      if (userId) await deletePack(userId, trip.id)
      setLocal(null)
      setRemoved(true)
      safe({ action: 'remove', result: 'ok', kb: 0 })
    } catch {
      setError('error')
      safe({ action: 'remove', result: 'error', kb: 0 })
    } finally { setBusy(false) }
  }

  const hasStored = !!stored.pack
  const tripId = trip?.id
  useEffect(() => {
    if (enabled && offlinePack && hasStored) safe({ action: 'open', result: 'ok', kb: 0 })
  }, [enabled, offlinePack, hasStored, tripId])

  if (!enabled || !offlinePack || !trip) return null

  return (
    <div data-tid="offlinePack" className="space-y-4">
      <section className="rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 p-4">
        <h2 className="text-lg font-semibold text-gray-900 dark:text-gray-100">{t('title')}</h2>
        <p className="text-sm text-gray-600 dark:text-gray-400 mt-1">{t('intro')}</p>
        {pack && (
          <p data-tid="offlinePack.status" className="mt-2 text-sm text-gray-800 dark:text-gray-200">
            {t('saved', { when: fmtDate(savedAt || pack.generated_at, { day: 'numeric', month: 'short', hour: 'numeric', minute: '2-digit' }) })}
            {' · '}{t('size', { kb })}
          </p>
        )}
        {local && !local.worker && (
          <p data-tid="offlinePack.tabnote" className="mt-1 text-sm text-amber-800 dark:text-amber-300">{t('tabOnly')}</p>
        )}
        {!online && <p data-tid="offlinePack.offline" className="mt-1 text-sm text-gray-600 dark:text-gray-400">{t('offlineNote')}</p>}
        {error && <p role="alert" data-tid="offlinePack.error" className="mt-1 text-sm text-red-700 dark:text-red-400">{t(`error.${error}`)}</p>}
        <div className="mt-3 flex flex-wrap gap-2">
          {pack ? (
            <>
              <button type="button" data-tid="offlinePack.refresh" disabled={busy || !online || !userId} onClick={() => save('refresh')}
                className={`${btn} bg-teal-700 hover:bg-teal-800 text-white`}>{t('refresh')}</button>
              <button type="button" data-tid="offlinePack.remove" disabled={busy} onClick={remove}
                className={`${btn} border border-gray-300 dark:border-gray-600 text-gray-800 dark:text-gray-200`}>{t('remove')}</button>
            </>
          ) : (
            <button type="button" data-tid="offlinePack.save" disabled={busy || !online || !userId} onClick={() => save('save')}
              className={`${btn} bg-teal-700 hover:bg-teal-800 text-white`}>{busy ? t('saving') : t('save')}</button>
          )}
        </div>
      </section>
      {pack && (
        <>
          <EmergencyNumbers emergency={pack.emergency} />
          <AddressCard card={pack.address_card} language={pack.phrases?.language} />
          <PhraseList phrases={pack.phrases} />
          <CurrencyConverter currency={pack.currency} />
        </>
      )}
    </div>
  )
}
