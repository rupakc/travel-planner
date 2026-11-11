import { useCallback, useEffect } from 'react'
import { Routes, Route, Navigate, useLocation, useNavigate } from 'react-router-dom'
import { useAuth } from './context/AuthContext'
import { SearchDataProvider, useSearchData } from './context/SearchDataContext'
import { AlertsProvider } from './context/AlertsContext'
import { notificationLink } from './utils/fareWatch'
import { loginPathFor } from './utils/returnPath'
import { track } from './utils/analytics'
import SearchPage          from './pages/SearchPage'
import ResultsPage         from './pages/ResultsPage'
import ChatPage            from './pages/ChatPage'
import PreferencesPage     from './pages/PreferencesPage'
import LoginPage           from './pages/LoginPage'
import ChangePasswordPage  from './pages/ChangePasswordPage'
import AdminPage           from './pages/AdminPage'
import SharePage           from './pages/SharePage'
import AlertsPage          from './pages/AlertsPage'
import NearbyPage          from './pages/NearbyPage'
import AlertToast          from './components/alerts/AlertToast'
import NavBar              from './components/ui/NavBar'
import FeedbackWidget      from './components/FeedbackWidget'
import AttributionFooter   from './components/ui/AttributionFooter'
import ConsentPrompt       from './components/ConsentPrompt'
import SignupPage          from './pages/SignupPage'
import VerifyEmailPage     from './pages/VerifyEmailPage'
import CheckEmailPage      from './pages/CheckEmailPage'
import ForgotPasswordPage  from './pages/ForgotPasswordPage'
import ResetPasswordPage   from './pages/ResetPasswordPage'
import OAuthCallbackPage   from './pages/OAuthCallbackPage'
import ChooseUsernamePage  from './pages/ChooseUsernamePage'
import AccountPage         from './pages/AccountPage'
import SettingsSync        from './components/account/SettingsSync'
import VerifyBanner        from './components/account/VerifyBanner'
import GameCelebration     from './components/game/GameCelebration'

// SearchDataProvider is intentionally placed inside Layout (not at App root)
// so that all search/results state is wiped on logout and starts fresh on login.

// Signed-out visits (e.g. a link from an alert email) go to login with the
// page kept in ?next=, and come back to it after signing in.
export function RequireAuth({ children }) {
  const { isAuthenticated, loading, requiresPasswordChange } = useAuth()
  const location = useLocation()
  if (loading) return <div className="min-h-screen flex items-center justify-center text-gray-500">Loading…</div>
  if (!isAuthenticated) return <Navigate to={loginPathFor(location)} state={{ from: location }} replace />
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

const PATH_LABEL = { '/': 'search', '/chat': 'chat', '/nearby': 'nearby', '/preferences': 'preferences', '/alerts': 'alerts', '/admin': 'admin', '/account': 'account' }
const KNOWN_PATHS = new Set(['/', '/chat', '/nearby', '/preferences', '/alerts', '/admin', '/account'])

function Layout() {
  const location = useLocation()
  const navigate = useNavigate()
  // A click on a native browser notification opens its watch
  const openAlert = useCallback((n) => navigate(notificationLink(n)), [navigate])

  useEffect(() => {
    track('page_view', PATH_LABEL[location.pathname] ?? 'unknown')
  }, [location.pathname])

  if (!KNOWN_PATHS.has(location.pathname)) {
    return <Navigate to="/" replace />
  }

  const path = location.pathname

  return (
    <SearchDataProvider>
     <AlertsProvider onOpenLink={openAlert}>
      <div className="min-h-screen bg-gradient-to-br from-sky-100 via-teal-50 to-emerald-100">
        <SettingsSync />
        <NavBar />
        <VerifyBanner />
        <FeedbackWidget />
        {/* SearchTab and ChatPage are always in the DOM — navigating away never unmounts them */}
        <div style={{ display: path === '/' ? 'block' : 'none' }}><SearchTab /></div>
        <div style={{ display: path === '/chat' ? 'block' : 'none' }}><ChatPage /></div>
        {path === '/preferences' && <PreferencesPage />}
        {path === '/alerts'      && <AlertsPage />}
        {/* Near me unmounts when left: its live results are never kept */}
        {path === '/nearby'      && <NearbyPage />}
        {path === '/account'     && <AccountPage />}
        {path === '/admin'       && <RequireAdmin><AdminPage /></RequireAdmin>}
        <AttributionFooter />
        <AlertToast />
        <GameCelebration />
      </div>
     </AlertsProvider>
    </SearchDataProvider>
  )
}

// Telemetry is called through import() and never awaited: it can't delay
// navigation, and a failing SDK is ignored. The SDK is not a separate chunk
// (ConsentPrompt -> telemetry/consent.js -> client.js import it statically,
// so it is in the main bundle); import() here only keeps the call async.
const telemetry = (fn) => {
  import('./telemetry/client').then(fn).catch(() => {})
}

export default function App() {
  const location = useLocation()
  const { isAuthenticated } = useAuth()

  useEffect(() => {
    telemetry((m) => m.screenView(location.pathname))
  }, [location.pathname])

  useEffect(() => {
    telemetry((m) => m.setUserPresent(isAuthenticated))
  }, [isAuthenticated])

  return (
    <>
    <Routes>
      <Route path="/login"           element={<LoginPage />} />
      <Route path="/signup"          element={<SignupPage />} />
      <Route path="/check-email"     element={<CheckEmailPage />} />
      <Route path="/verify"          element={<VerifyEmailPage />} />
      <Route path="/forgot-password" element={<ForgotPasswordPage />} />
      <Route path="/reset-password"  element={<ResetPasswordPage />} />
      <Route path="/auth/callback"   element={<OAuthCallbackPage />} />
      <Route path="/auth/username"   element={<ChooseUsernamePage />} />
      {/* Public share link — works without login */}
      <Route path="/share/:token"    element={<SharePage />} />
      <Route path="/change-password" element={<RequireAuth><ChangePasswordPage /></RequireAuth>} />
      <Route path="/*"               element={<RequireAuth><Layout /></RequireAuth>} />
    </Routes>
    <ConsentPrompt />
    </>
  )
}
