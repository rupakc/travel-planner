import { useEffect } from 'react'
import { useClientConfig, featureOn } from './useClientConfig'

// The journey shell (Trips hub, trip screens, Play/You) is on when the server
// has the trips API (`features.trips`) and either enables the UI
// (`features.journey`) or this browser opted in with localStorage
// tp_journey = "1". tp_journey = "0" always turns it off. An older backend
// has no `features.trips`, so the classic shell stays, whatever is stored.
const OVERRIDE_KEY = 'tp_journey'

function storedOverride() {
  try { return window.localStorage.getItem(OVERRIDE_KEY) } catch { return null }
}

/** -> {enabled, tripsApi, offlinePack, source: 'config'|'override'|'off'} */
export function journeyState(config, override = storedOverride()) {
  const tripsApi = featureOn(config, 'trips')
  const server = featureOn(config, 'journey')
  const enabled = tripsApi && (server || override === '1') && override !== '0'
  return {
    enabled,
    tripsApi,
    offlinePack: tripsApi && featureOn(config, 'offline_pack'),
    source: enabled ? (server ? 'config' : 'override') : 'off',
  }
}

let reported = false

function report(props) {
  import('../telemetry/client').then((m) => m.emit('journey_shell', props)).catch(() => {})
}

export function useJourney() {
  const { config, loaded } = useClientConfig()
  const { enabled, tripsApi, offlinePack, source } = journeyState(loaded ? config : {})

  // Once per page load, after /config has answered.
  useEffect(() => {
    if (!loaded || reported) return
    reported = true
    report({ enabled, source })
  }, [loaded, enabled, source])

  return { enabled, tripsApi, offlinePack, loaded }
}
