import { useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { useAuth } from '../../context/AuthContext'
import { Search, MessageCircle, Settings, User, LogOut, ShieldCheck, Menu, X, Plane } from 'lucide-react'

const BASE_TABS = [
  { path: '/',            label: 'Search',      icon: Search },
  { path: '/chat',        label: 'Chat',         icon: MessageCircle },
  { path: '/preferences', label: 'Preferences',  icon: Settings },
]

export default function NavBar() {
  const { user, logout, isAdmin } = useAuth()
  const location = useLocation()
  const navigate = useNavigate()
  const [menuOpen, setMenuOpen] = useState(false)

  const tabs = isAdmin
    ? [...BASE_TABS, { path: '/admin', label: 'Admin', icon: ShieldCheck }]
    : BASE_TABS

  const NavLinks = ({ onClick }) => tabs.map(({ path, label, icon: Icon }) => {
    const isActive = location.pathname === path
    return (
      <button
        key={path}
        onClick={() => { navigate(path); onClick?.() }}
        className={`flex items-center gap-1.5 px-3.5 py-1.5 rounded-md text-sm font-medium transition-all ${
          isActive
            ? 'bg-white text-teal-700 shadow-sm'
            : 'text-slate-400 hover:text-slate-600 hover:bg-white/50'
        }`}
      >
        <Icon size={14} />
        <span>{label}</span>
      </button>
    )
  })

  return (
    <>
      <div className="h-14 flex items-center justify-between px-4 sm:px-6 bg-white/85 backdrop-blur-md border-b border-gray-100 sticky top-0 z-50">
        {/* Wordmark + Desktop tabs */}
        <div className="hidden sm:flex items-center gap-1">
          <div className="hidden sm:flex items-center gap-2 mr-4 shrink-0">
            <div className="w-7 h-7 rounded-lg bg-gradient-to-br from-teal-500 to-teal-700 flex items-center justify-center shadow-sm">
              <Plane size={14} className="text-white" strokeWidth={2.5} />
            </div>
            <span className="font-display font-bold text-slate-800 text-sm tracking-tight">Voyager</span>
          </div>
          <div className="flex items-center gap-1 bg-slate-100/80 rounded-xl p-0.5">
            <NavLinks />
          </div>
        </div>

        {/* Mobile hamburger */}
        <button
          className="sm:hidden p-2 text-slate-600 hover:text-slate-800"
          onClick={() => setMenuOpen(o => !o)}
          aria-label="Menu"
        >
          {menuOpen ? <X size={20} /> : <Menu size={20} />}
        </button>

        {/* User info */}
        {user && (
          <div className="flex items-center gap-2 text-slate-600 text-sm">
            <User size={14} />
            <span className="font-medium hidden sm:inline">{user.username}</span>
            {isAdmin && <span className="hidden sm:inline px-1.5 py-0.5 bg-purple-100 text-purple-700 text-xs rounded-full">Admin</span>}
            <button
              onClick={logout}
              className="ml-1 text-slate-400 hover:text-slate-700 transition-colors"
              title="Sign out"
            >
              <LogOut size={14} />
            </button>
          </div>
        )}
      </div>

      {/* Mobile nav drawer */}
      {menuOpen && (
        <div className="sm:hidden bg-white/95 backdrop-blur-md border-b border-gray-100 px-4 py-3 flex flex-col gap-1 sticky top-14 z-40 shadow-md">
          <NavLinks onClick={() => setMenuOpen(false)} />
        </div>
      )}
    </>
  )
}
