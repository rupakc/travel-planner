import { useEffect } from 'react'
import { Routes, Route, Navigate, useLocation } from 'react-router-dom'
import { useAuth } from './context/AuthContext'
import { SearchDataProvider, useSearchData } from './context/SearchDataContext'
import { track } from './utils/analytics'
import SearchPage          from './pages/SearchPage'
import ResultsPage         from './pages/ResultsPage'
import ChatPage            from './pages/ChatPage'
import PreferencesPage     from './pages/PreferencesPage'
import LoginPage           from './pages/LoginPage'
import ChangePasswordPage  from './pages/ChangePasswordPage'
import AdminPage           from './pages/AdminPage'
import SharePage           from './pages/SharePage'
import NavBar              from './components/ui/NavBar'
import FeedbackWidget      from './components/FeedbackWidget'

// SearchDataProvider is intentionally placed inside Layout (not at App root)
// so that all search/results state is wiped on logout and starts fresh on login.

function RequireAuth({ children }) {
  const { isAuthenticated, loading, requiresPasswordChange } = useAuth()
  const location = useLocation()
  if (loading) return <div className="min-h-screen flex items-center justify-center text-gray-500">Loading…</div>
  if (!isAuthenticated) return <Navigate to="/login" replace />
  if (requiresPasswordChange && location.pathname !== '/change-password') {
    return <Navigate to="/change-password" replace />
  }
  return children
}

function RequireAdmin({ children }) {
  const { isAdmin, loading } = useAuth()
  if (loading) return null
  return isAdmin ? children : <Navigate to="/" replace />
}

// Search and Results stay mounted at all times so streaming state is never lost
// when the user navigates to Chat/Preferences and back.
function SearchTab() {
  const { hasSearchResults } = useSearchData()
  return (
    <>
      <div style={{ display: hasSearchResults ? 'none' : 'block' }}><SearchPage /></div>
      <div style={{ display: hasSearchResults ? 'block' : 'none' }}><ResultsPage /></div>
    </>
  )
}

const PATH_LABEL = { '/': 'search', '/chat': 'chat', '/preferences': 'preferences', '/admin': 'admin' }
const KNOWN_PATHS = new Set(['/', '/chat', '/preferences', '/admin'])

function Layout() {
  const location = useLocation()

  useEffect(() => {
    track('page_view', PATH_LABEL[location.pathname] ?? 'unknown')
  }, [location.pathname])

  if (!KNOWN_PATHS.has(location.pathname)) {
    return <Navigate to="/" replace />
  }

  const path = location.pathname

  return (
    <SearchDataProvider>
      <div className="min-h-screen bg-gradient-to-br from-sky-100 via-teal-50 to-emerald-100">
        <NavBar />
        <FeedbackWidget />
        {/* SearchTab and ChatPage are always in the DOM — navigating away never unmounts them */}
        <div style={{ display: path === '/' ? 'block' : 'none' }}><SearchTab /></div>
        <div style={{ display: path === '/chat' ? 'block' : 'none' }}><ChatPage /></div>
        {path === '/preferences' && <PreferencesPage />}
        {path === '/admin'       && <RequireAdmin><AdminPage /></RequireAdmin>}
      </div>
    </SearchDataProvider>
  )
}

export default function App() {
  return (
    <Routes>
      <Route path="/login"           element={<LoginPage />} />
      {/* Public share link — works without login */}
      <Route path="/share/:token"    element={<SharePage />} />
      <Route path="/change-password" element={<RequireAuth><ChangePasswordPage /></RequireAuth>} />
      <Route path="/*"               element={<RequireAuth><Layout /></RequireAuth>} />
    </Routes>
  )
}
