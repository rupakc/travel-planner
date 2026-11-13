import { useClientConfig } from './useClientConfig'
import { useAccountSettings, useSettingsLoading } from '../components/account/SettingsSync'

// `features.social` is 0|1 in /config (docs/Social-API.md). An older backend
// has no such key, so the feed, profiles and the publish entry points stay hidden.
export const socialOn = (config) => {
  const v = config?.features?.social
  return v === 1 || v === true
}

/**
 * -> {enabled, loaded}. `hide_community` (account setting; a missing key, as on
 * an older backend, means shown) switches every social surface off, and the
 * route guard waits while the signed-in user's settings are still loading.
 */
export function useSocialEnabled() {
  const { config, loaded } = useClientConfig()
  const { settings } = useAccountSettings()
  const settingsLoading = useSettingsLoading()
  const hidden = settings?.hide_community === true
  return { enabled: loaded && !settingsLoading && !hidden && socialOn(config), loaded: loaded && !settingsLoading }
}
