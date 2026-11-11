import { useEffect, useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import OnboardingTour from '../OnboardingTour'
import useFirstRunTour from '../../hooks/useFirstRunTour'
import { useJourney } from '../../hooks/useJourney'

export const REPLAY_EVENT = 'voyager:replay-journey-tour'
const START_DELAY_MS = 800
const ANCHORS = ['nav-trips', 'nav-explore', 'nav-alerts', 'nav-play', 'nav-you', 'trips-create']
const STEP_KEYS = { 'nav-trips': 'trips', 'nav-explore': 'explore', 'nav-alerts': 'alerts', 'nav-play': 'play', 'nav-you': 'you', 'trips-create': 'create' }

/**
 * Coach marks for the journey tabs. Opens once, after onboarding is done,
 * and again on the `voyager:replay-journey-tour` window event ("Show me
 * around" in You). Its seen flag is separate from the classic Search tour
 * (the username is namespaced), and no `token` is passed so it never
 * reports onboarding. Steps whose anchor is missing or hidden are skipped
 * by OnboardingTour (it targets the first visible match, so the phone
 * BottomTabs entry or the desktop tab, whichever is on screen).
 */
export default function JourneyTour({ username, visible = true, onboardingDone = false }) {
  const { t } = useTranslation('coach')
  const { enabled } = useJourney()

  const steps = useMemo(() => ANCHORS.map((a) => ({
    id: a,
    target: `[data-tour="${a}"]`,
    title: t(`steps.${STEP_KEYS[a]}.title`),
    body: t(`steps.${STEP_KEYS[a]}.body`),
  })), [t])

  const active = enabled && !!visible
  const tour = useFirstRunTour({
    username: username ? `journey:${username}` : undefined,
    visible: active,
    eligible: !!onboardingDone,
    delayMs: START_DELAY_MS,
  })
  const { start } = tour

  useEffect(() => {
    if (!active) return undefined
    const onReplay = () => start()
    window.addEventListener(REPLAY_EVENT, onReplay)
    return () => window.removeEventListener(REPLAY_EVENT, onReplay)
  }, [active, start])

  if (!active) return null
  return <OnboardingTour open={tour.open} steps={steps} onClose={tour.close} />
}
