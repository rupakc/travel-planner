// Sends a signed-in user who has not finished onboarding to /onboarding,
// once per browser session (sessionStorage tp_onboarding_seen), and only with
// the journey on. Finishing or skipping sets `done`, so it never comes back.
// A 404 (older backend) or any error from /account does nothing.
import { useEffect, useRef } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { useJourney } from '../../hooks/useJourney'
import { useAuth } from '../../context/AuthContext'
import { getAccount } from '../../services/accountApi'

const SEEN_KEY = 'tp_onboarding_seen'

export function onboardingSeen() {
  try { return window.sessionStorage.getItem(SEEN_KEY) !== null } catch { return false }
}

export function markOnboardingSeen() {
  try { window.sessionStorage.setItem(SEEN_KEY, '1') } catch { /* storage blocked */ }
}

export default function OnboardingGate() {
  const { enabled } = useJourney()
  const { token, user } = useAuth()
  const { pathname } = useLocation()
  const navigate = useNavigate()
  const asked = useRef(false)
  const mounted = useRef(true)

  useEffect(() => {
    mounted.current = true
    return () => { mounted.current = false }
  }, [])

  useEffect(() => {
    if (!enabled || !token || !user || asked.current) return
    if (pathname === '/onboarding' || onboardingSeen()) return
    asked.current = true
    getAccount(token)
      .then((acc) => {
        if (!mounted.current || acc?.onboarding?.done !== false || onboardingSeen()) return
        markOnboardingSeen()
        navigate('/onboarding')
      })
      .catch(() => { /* 404 (no accounts API) or offline: stay put */ })
  }, [enabled, token, user, pathname, navigate])

  return null
}
