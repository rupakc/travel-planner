import { useClientConfig } from './useClientConfig'

// Price alerts 2.0 (story, drop moment, savings, one-tap watch, prefs) is on
// when the server has the alerts API (`features.alerts_api === 2`) and either
// enables the UI (`features.price_alerts_v2`) or this browser opted in with
// localStorage tp_alerts2 = "1". tp_alerts2 = "0" always turns it off. An
// older backend has no `features.alerts_api`, so the classic page stays,
// whatever is stored.
const OVERRIDE_KEY = 'tp_alerts2'

function storedOverride() {
  try { return window.localStorage.getItem(OVERRIDE_KEY) } catch { return null }
}

/** -> {on, livePrices, source: 'config'|'override'|'off'} */
export function alertsV2State(config, override = storedOverride()) {
  const api = config?.features?.alerts_api === 2
  const server = config?.features?.price_alerts_v2 === true
  const on = api && (server || override === '1') && override !== '0'
  return {
    on,
    livePrices: on && config?.features?.live_prices === true,
    source: on ? (server ? 'config' : 'override') : 'off',
  }
}

export function useAlertsV2() {
  const { config, loaded } = useClientConfig()
  return alertsV2State(loaded ? config : {})
}
