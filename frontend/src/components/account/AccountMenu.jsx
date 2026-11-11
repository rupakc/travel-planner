import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { UserCog, Settings, LogOut } from 'lucide-react'
import { useAuth } from '../../context/AuthContext'
import Avatar from './Avatar'

/** NavBar avatar button with Account, Preferences and Sign out. */
export default function AccountMenu() {
  const { user, logout } = useAuth()
  const navigate = useNavigate()
  const { t } = useTranslation('profile')
  const [open, setOpen] = useState(false)
  const ref = useRef(null)

  useEffect(() => {
    if (!open) return undefined
    const onDown = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false) }
    const onKey = (e) => { if (e.key === 'Escape') setOpen(false) }
    document.addEventListener('mousedown', onDown)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDown)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  if (!user) return null
  const go = (path) => { setOpen(false); navigate(path) }
  const item = 'flex w-full items-center gap-2 px-3 py-2 text-sm text-left text-slate-700 dark:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-700'

  return (
    <div className="relative" ref={ref}>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={t('menu.button')}
        title={t('menu.button')}
        data-tid="account.menu"
        className="rounded-full focus:outline-none focus-visible:ring-2 focus-visible:ring-sky-500"
      >
        <Avatar user={user} size={28} />
      </button>
      {open && (
        <div
          role="menu"
          className="absolute right-0 mt-2 w-48 max-w-[calc(100vw-2rem)] z-50 overflow-hidden rounded-lg border border-slate-200 bg-white py-1 shadow-lg dark:border-slate-700 dark:bg-slate-800"
        >
          <div className="px-3 py-2 border-b border-slate-100 dark:border-slate-700">
            <div className="truncate text-sm font-medium text-slate-800 dark:text-slate-100">{user.display_name || user.username}</div>
            <div className="truncate text-xs text-slate-500 dark:text-slate-400">@{user.username}</div>
          </div>
          <button type="button" role="menuitem" data-tid="account.menu.account" className={item} onClick={() => go('/account')}>
            <UserCog size={14} />{t('menu.account')}
          </button>
          <button type="button" role="menuitem" data-tid="account.menu.preferences" className={item} onClick={() => go('/preferences')}>
            <Settings size={14} />{t('menu.preferences')}
          </button>
          <button type="button" role="menuitem" data-tid="nav.signOut" className={item} onClick={() => { setOpen(false); logout() }}>
            <LogOut size={14} />{t('menu.signOut')}
          </button>
        </div>
      )}
    </div>
  )
}
