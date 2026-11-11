import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { AuthProvider } from './context/AuthContext'
import App from './App.jsx'
import { ThemeProvider } from './theme/ThemeContext'
import { initI18n } from './i18n'
import { watchFetch } from './services/sessionRevoked'
import './index.css'
import 'leaflet/dist/leaflet.css'

const queryClient = new QueryClient()

// Every main-thread fetch reports a 401 session_revoked to AuthContext (the
// axios clients and the SSE workers report on their own).
watchFetch()

// English is bundled, so the first render is never blank; another language
// re-renders the tree once its chunk arrives.
initI18n()

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <ThemeProvider>
      <QueryClientProvider client={queryClient}>
        <BrowserRouter>
          <AuthProvider>
            <App />
          </AuthProvider>
        </BrowserRouter>
      </QueryClientProvider>
    </ThemeProvider>
  </React.StrictMode>,
)

// Telemetry starts after the first render, in idle time; a failure to start
// it is ignored. The SDK code itself is already in the main bundle (pulled in
// statically via ConsentPrompt -> telemetry/consent.js -> client.js), so this
// defers the work, not the download.
const startTelemetry = () => {
  import('./telemetry/client')
    .then((m) => m.initTelemetry({ appVersion: import.meta.env.VITE_APP_VERSION || '0.0.0' }))
    .catch(() => {})
}
try {
  if (typeof window.requestIdleCallback === 'function') window.requestIdleCallback(startTelemetry, { timeout: 5000 })
  else setTimeout(startTelemetry, 1)
} catch { /* never block the app over telemetry */ }
