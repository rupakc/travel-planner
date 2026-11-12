import { useClientConfig } from './useClientConfig'

// `features.social` is 0|1 in /config (docs/Social-API.md). An older backend
// has no such key, so the feed, profiles and the publish entry points stay hidden.
export const socialOn = (config) => {
  const v = config?.features?.social
  return v === 1 || v === true
}

/** -> {enabled, loaded} */
export function useSocialEnabled() {
  const { config, loaded } = useClientConfig()
  return { enabled: loaded && socialOn(config), loaded }
}
