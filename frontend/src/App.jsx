import { useCallback, useEffect, useState } from 'react'
import { Routes, Route, Navigate, useLocation, useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
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
import TripsPage           from './pages/TripsPage'
import TripPage            from './pages/TripPage'
import PlayPage            from './pages/PlayPage'
import YouPage             from './pages/YouPage'
import OnboardingPage      from './pages/OnboardingPage'
import OnboardingGate      from './components/onboarding/OnboardingGate'
import JourneyTour         from './components/trips/JourneyTour'
import { getAccount }      from './services/accountApi'
import OfflineBanner       from './components/offline/OfflineBanner'
import I18nRouteGate       from './components/I18nRouteGate'
import { useJourney }      from './hooks/useJourney'
import { useAlertsV2 }     from './hooks/useAlertsV2'
import DropMoment          from './components/alerts2/DropMoment'
import { useHasTrips }     from './hooks/useHasTrips'
import { matchTripPath, matchH2hPath } from './journey/paths'

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

const PATH_LABEL = {
  '/': 'search', '/chat': 'chat', '/nearby': 'nearby', '/preferences': 'preferences', '/alerts': 'alerts',
  '/admin': 'admin', '/account': 'account',
  '/trips': 'trips', '/explore': 'explore', '/play': 'play', '/you': 'you',
}
const CLASSIC_PATHS = new Set(['/', '/chat', '/nearby', '/preferences', '/alerts', '/admin', '/account'])
const JOURNEY_PATHS = new Set(['/trips', '/explore', '/play', '/you'])

// The journey-only paths: /trips, /explore, /play, /you and /trips/<id>(/<tab>).
const isJourneyPath = (path) => JOURNEY_PATHS.has(path) || matchTripPath(path) !== null || matchH2hPath(path) !== null

// `journey`: true, false, or null while /config is still loading (a journey
// deep link waits instead of being redirected away).
function knownPath(path, journey) {
  if (CLASSIC_PATHS.has(path)) return true
  if (!isJourneyPath(path)) return false
  return journey !== false
}

const pageLabel = (path) => PATH_LABEL[path] ?? (matchTripPath(path) ? 'trip' : matchH2hPath(path) ? 'play' : 'unknown')

function Pending() {
  const { t } = useTranslation('journey')
  return (
    <div data-tid="journey.homeLoading" role="status" aria-label={t('load.loading')} className="max-w-5xl mx-auto px-4 py-8 space-y-4">
      <div className="h-8 w-48 rounded-lg bg-white/60 animate-pulse motion-reduce:animate-none" />
      <div className="h-32 rounded-2xl bg-white/60 animate-pulse motion-reduce:animate-none" />
      <div className="h-32 rounded-2xl bg-white/60 animate-pulse motion-reduce:animate-none" />
    </div>
  )
}

// Journey-only full-screen routes: the classic shell sends them home.
function JourneyOnly({ children }) {
  const { enabled, loaded } = useJourney()
  if (!loaded) return null
  return enabled ? children : <Navigate to="/" replace />
}

// Coach marks for the journey tabs, once the account's onboarding is done.
function JourneyCoach({ visible }) {
  const { token, user } = useAuth()
  const [done, setDone] = useState(false)
  useEffect(() => {
    let live = true
    Promise.resolve(getAccount(token))
      .then((a) => { if (live) setDone(a?.onboarding?.done === true) })
      .catch(() => {})
    return () => { live = false }
  }, [token])
  return <JourneyTour username={user?.username} visible={visible} onboardingDone={done} />
}

function Layout() {
  const location = useLocation()
  const navigate = useNavigate()
  const { enabled: journeyOn, loaded: journeyLoaded } = useJourney()
  const { on: alertsV2 } = useAlertsV2()
  const { hasTrips } = useHasTrips()
  // A click on a native browser notification opens its watch
  const openAlert = useCallback((n) => navigate(notificationLink(n)), [navigate])

  useEffect(() => {
    track('page_view', pageLabel(location.pathname))
  }, [location.pathname])

  const path = location.pathname
  const journey = journeyLoaded ? journeyOn : null
  if (!knownPath(path, journey)) {
    return <Navigate to="/" replace />
  }

  // With the journey on, `/` is the Trips hub for a user with a trip and
  // Explore (the search) for everyone else; a skeleton while that is checked.
  const home = !journeyOn ? 'search' : hasTrips === true ? 'trips' : hasTrips === false ? 'search' : 'pending'
  const showSearch = (path === '/' && home === 'search') || (journeyOn && path === '/explore')
  const trip = journeyOn ? matchTripPath(path) : null
  const waiting = journey === null && isJourneyPath(path)

  return (
    <SearchDataProvider>
     <AlertsProvider onOpenLink={openAlert}>
      <div className={`min-h-screen bg-gradient-to-br from-sky-100 via-teal-50 to-emerald-100${journeyOn ? ' pb-[calc(4rem+env(safe-area-inset-bottom))] sm:pb-0' : ''}`}>
        <SettingsSync />
        <NavBar />
        <VerifyBanner />
        <OfflineBanner />
        <OnboardingGate />
        {journeyOn && <JourneyCoach visible />}
        <FeedbackWidget />
        {/* SearchTab and ChatPage are always in the DOM — navigating away never unmounts them */}
        <div style={{ display: showSearch ? 'block' : 'none' }}><SearchTab /></div>
        <div style={{ display: path === '/chat' ? 'block' : 'none' }}><ChatPage /></div>
        <I18nRouteGate pathname={path}>
          {path === '/preferences' && <PreferencesPage />}
          {path === '/alerts'      && <AlertsPage />}
          {/* Near me unmounts when left: its live results are never kept */}
          {path === '/nearby'      && <NearbyPage />}
          {path === '/account'     && <AccountPage />}
          {path === '/admin'       && <RequireAdmin><AdminPage /></RequireAdmin>}
          {journeyOn && path === '/' && home === 'trips'   && <TripsPage />}
          {journeyOn && path === '/' && home === 'pending' && <Pending />}
          {journeyOn && path === '/trips' && <TripsPage />}
          {trip && <TripPage tripId={trip.id} tab={trip.tab} />}
          {journeyOn && path === '/play' && <PlayPage />}
          {journeyOn && matchH2hPath(path) && <PlayPage h2hId={matchH2hPath(path)} />}
          {journeyOn && path === '/you'  && <YouPage />}
          {waiting && <Pending />}
        </I18nRouteGate>
        <AttributionFooter />
        <AlertToast />
        {alertsV2 && <DropMoment />}
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
      {/* Journey onboarding: full screen, outside the Layout (no nav) */}
      <Route path="/onboarding"      element={<RequireAuth><JourneyOnly><OnboardingPage /></JourneyOnly></RequireAuth>} />
      <Route path="/*"               element={<RequireAuth><Layout /></RequireAuth>} />
    </Routes>
    <ConsentPrompt />
    </>
  )
}
