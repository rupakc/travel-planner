import { useTranslation } from 'react-i18next'

// Phone tab bar (< 640 px) for the journey shell; NavBar passes the tabs and
// which one is active. Each tab is at least 44 px tall.
export default function BottomTabs({ tabs, isActive, onSelect, unread = 0 }) {
  const { t } = useTranslation(['journey', 'common'])
  return (
    <nav
      aria-label={t('common:nav.menu')}
      data-tid="bottomTabs"
      className="sm:hidden fixed bottom-0 inset-x-0 z-50 flex bg-white/95 backdrop-blur-md border-t border-gray-100 pb-[env(safe-area-inset-bottom)]"
    >
      {tabs.map(({ path, key, tour, label, icon: Icon }) => {
        const active = isActive(path)
        const hasUnread = key === 'alerts' && unread > 0
        return (
          <button
            key={path}
            type="button"
            data-tour={`nav-${tour}`}
            data-tid={`bottomTabs.${key}`}
            aria-current={active ? 'page' : undefined}
            aria-label={hasUnread ? t('common:nav.alertsUnread', { count: unread }) : undefined}
            onClick={() => onSelect(path)}
            className={`relative flex min-h-[56px] min-w-0 flex-1 flex-col items-center justify-center gap-0.5 text-[11px] font-medium ${
              active ? 'text-teal-700' : 'text-slate-500 hover:text-slate-700'
            }`}
          >
            <Icon size={20} aria-hidden="true" />
            <span className="max-w-full truncate px-0.5">{label}</span>
            {hasUnread && <span className="absolute top-2 right-1/4 h-1.5 w-1.5 rounded-full bg-sky-500" aria-hidden="true" />}
          </button>
        )
      })}
    </nav>
  )
}
