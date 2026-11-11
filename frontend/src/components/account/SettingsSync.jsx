export const DEFAULT_SETTINGS = {
  language: null, theme: 'system', currency: 'USD', units: 'metric', timezone: null,
  hide_game: false, hide_community: false, profile_visibility: 'public', telemetry_opt_out: false,
}

export function useAccountSettings() {
  return { settings: DEFAULT_SETTINGS, update: () => {} }
}

export default function SettingsSync() { return null }
