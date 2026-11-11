import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Download, Trash2 } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { useAuth } from '../../context/AuthContext'
import { exportAccount, deleteAccount } from '../../services/accountApi'
import { errorText } from '../../services/apiError'
import { emit } from '../../telemetry/client'

const todayStamp = () => new Date().toISOString().slice(0, 10)

export default function DataSection({ account }) {
  const { t } = useTranslation('accountData')
  const { t: tAll } = useTranslation()
  const { token, logout } = useAuth()
  const navigate = useNavigate()

  const [exporting, setExporting] = useState(false)
  const [exportError, setExportError] = useState('')
  const [open, setOpen] = useState(false)
  const [value, setValue] = useState('')
  const [deleting, setDeleting] = useState(false)
  const [deleteError, setDeleteError] = useState('')
  const inputRef = useRef(null)

  useEffect(() => {
    if (!open) return undefined
    inputRef.current?.focus()
    const onKey = (e) => { if (e.key === 'Escape' && !deleting) setOpen(false) }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [open, deleting])

  if (!account) return null
  const username = account.user?.username || ''
  const hasPassword = !!account.user?.has_password
  const matches = hasPassword ? value.length > 0 : value.trim() === username && username !== ''

  const download = async () => {
    setExporting(true)
    setExportError('')
    let url
    try {
      const blob = await exportAccount(token)
      url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `voyager-export-${username}-${todayStamp()}.json`
      document.body.appendChild(a)
      a.click()
      a.remove()
      emit('account_action', { action: 'export' })
    } catch (err) {
      setExportError(err?.status ? errorText(tAll, err) : t('export.error'))
    } finally {
      if (url) URL.revokeObjectURL(url)
      setExporting(false)
    }
  }

  const close = () => { if (!deleting) { setOpen(false); setValue(''); setDeleteError('') } }

  const confirmDelete = async (e) => {
    e.preventDefault()
    if (!matches || deleting) return
    setDeleting(true)
    setDeleteError('')
    try {
      await deleteAccount(token, hasPassword ? { password: value } : { confirm_username: value.trim() })
      emit('account_action', { action: 'delete' })
      navigate('/login', { replace: true, state: { accountDeleted: true } })
      logout()
    } catch (err) {
      setDeleteError(errorText(tAll, err))
      setDeleting(false)
    }
  }

  const items = [1, 2, 3, 4].map((n) => t(`delete.item${n}`))

  return (
    <section data-tid="account.data" className="bg-white dark:bg-gray-900 rounded-2xl ring-1 ring-gray-100 dark:ring-gray-800 p-6 mb-6">
      <h2 className="text-lg font-semibold text-gray-900 dark:text-gray-100">{t('title')}</h2>
      <p className="text-sm text-gray-600 dark:text-gray-400 mt-1">{t('intro')}</p>

      <div className="mt-4 flex flex-wrap gap-3">
        <button type="button" data-tid="account.data.export" onClick={download} disabled={exporting}
          className="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-teal-600 text-white text-sm font-medium hover:bg-teal-700 disabled:opacity-60">
          <Download size={16} aria-hidden="true" />
          {exporting ? t('export.working') : t('export.button')}
        </button>
        <button type="button" data-tid="account.data.delete" onClick={() => setOpen(true)}
          className="inline-flex items-center gap-2 px-4 py-2 rounded-lg border border-red-300 text-red-700 dark:border-red-800 dark:text-red-300 text-sm font-medium hover:bg-red-50 dark:hover:bg-red-950">
          <Trash2 size={16} aria-hidden="true" />
          {t('delete.button')}
        </button>
      </div>
      <p className="text-xs text-gray-500 dark:text-gray-400 mt-2">{t('export.hint')}</p>
      {exportError && <p role="alert" data-tid="account.data.export-error" className="text-sm text-red-700 dark:text-red-300 mt-2">{exportError}</p>}

      {open && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 px-4"
          onMouseDown={(e) => { if (e.target === e.currentTarget) close() }}>
          <form role="dialog" aria-modal="true" aria-labelledby="account-delete-title" data-tid="account.data.dialog"
            onSubmit={confirmDelete}
            className="w-full max-w-md bg-white dark:bg-gray-900 rounded-2xl shadow-2xl p-6 space-y-4">
            <h3 id="account-delete-title" className="text-lg font-semibold text-gray-900 dark:text-gray-100">{t('delete.title')}</h3>
            <div className="text-sm text-gray-700 dark:text-gray-300">
              <p>{t('delete.intro')}</p>
              <ul className="list-disc pl-5 mt-1 space-y-0.5">
                {items.map((item) => <li key={item}>{item}</li>)}
              </ul>
              <p className="mt-2 font-medium text-red-700 dark:text-red-300">{t('delete.warn')}</p>
            </div>
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300">
              {hasPassword ? t('delete.password') : t('delete.username', { username })}
              <input ref={inputRef} data-tid="account.data.confirm-input"
                type={hasPassword ? 'password' : 'text'}
                autoComplete={hasPassword ? 'current-password' : 'off'}
                value={value} onChange={(e) => setValue(e.target.value)}
                className="mt-1 w-full px-3 py-2 border border-gray-300 dark:border-gray-700 rounded-lg text-sm text-gray-900 dark:text-gray-100 dark:bg-gray-800" />
            </label>
            {deleteError && <p role="alert" data-tid="account.data.delete-error" className="text-sm text-red-700 dark:text-red-300">{deleteError}</p>}
            <div className="flex justify-end gap-3">
              <button type="button" data-tid="account.data.cancel" onClick={close} disabled={deleting}
                className="px-4 py-2 rounded-lg text-sm text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-800">
                {t('delete.cancel')}
              </button>
              <button type="submit" data-tid="account.data.confirm" disabled={!matches || deleting}
                className="px-4 py-2 rounded-lg bg-red-600 text-white text-sm font-medium hover:bg-red-700 disabled:opacity-50">
                {deleting ? t('delete.working') : t('delete.confirm')}
              </button>
            </div>
          </form>
        </div>
      )}
    </section>
  )
}
