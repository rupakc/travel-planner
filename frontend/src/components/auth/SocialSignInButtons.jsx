import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Info } from 'lucide-react'
import { getAuthProviders } from '../../services/api'
import { navigateTo } from './navigate'
import { AppleIcon, GoogleIcon, FacebookIcon, GitHubIcon } from './providerIcons'

// Brand names are not translated. Button colours follow each provider's
// published guidance, with the dark-theme variant they publish. They are
// literal hex: palette names (white, neutral-*, …) are CSS variables that
// html.dark remaps (white turns navy), which made Apple vanish in dark mode.
// In dark, Apple is the white button Apple's guidelines ask for, with a
// light edge so it reads as a button on the dark card.
const PROVIDERS = [
  { id: 'apple', name: 'Apple', Icon: AppleIcon,
    cls: 'bg-black text-[#ffffff] border-black hover:bg-[#262626] dark:bg-[#ffffff] dark:text-[#000000] dark:border-[#d4d4d4] dark:hover:bg-[#e5e5e5]' },
  { id: 'google', name: 'Google', Icon: GoogleIcon,
    cls: 'bg-[#ffffff] text-[#1f1f1f] border-[#747775] hover:bg-[#f8fafb] dark:bg-[#131314] dark:text-[#e3e3e3] dark:border-[#8e918f] dark:hover:bg-[#1e1f20]' },
  { id: 'facebook', name: 'Facebook', Icon: FacebookIcon,
    cls: 'bg-[#1877F2] text-[#ffffff] border-[#1877F2] hover:bg-[#166fe5]' },
  { id: 'github', name: 'GitHub', Icon: GitHubIcon,
    cls: 'bg-[#24292f] text-[#ffffff] border-[#24292f] hover:bg-[#32383f] dark:bg-[#f6f8fa] dark:text-[#24292f] dark:border-[#d0d7de] dark:hover:bg-[#ffffff]' },
]

// Only a same-origin OAuth start path is ever navigated to.
// The URL parser folds dot segments (including %2e%2e) and treats a backslash
// as a slash, so the resolved path is what gets checked; the raw string must
// also be free of `..` and backslashes.
function safeStart(url) {
  if (typeof url !== 'string' || url.includes('..') || url.includes('\\')) return null
  try {
    const u = new URL(url, window.location.origin)
    if (u.origin !== window.location.origin || !u.pathname.startsWith('/api/auth/')) return null
    return u.pathname + u.search
  } catch {
    return null
  }
}

export default function SocialSignInButtons({ mode = 'signin' }) {
  const { t } = useTranslation('auth')
  const [providers, setProviders] = useState({})
  const [soon, setSoon] = useState(null)

  useEffect(() => {
    let alive = true
    getAuthProviders()
      .then((list) => {
        if (!alive || !Array.isArray(list)) return
        setProviders(Object.fromEntries(list.map((p) => [p?.id, p])))
      })
      .catch(() => {})
    return () => { alive = false }
  }, [])

  const choose = (p) => {
    const info = providers[p.id]
    const start = info?.configured ? safeStart(info.start_url) : null
    if (start) { setSoon(null); navigateTo(start); return }
    setSoon(p.name)
  }

  return (
    <div data-mode={mode} className="space-y-2">
      {PROVIDERS.map((p) => (
        <button key={p.id} type="button" data-tid={`auth.provider.${p.id}`}
          onClick={() => choose(p)}
          className={`w-full flex items-center justify-center gap-2.5 py-2.5 px-3 border rounded-lg text-sm font-medium transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-400 ${p.cls}`}>
          <p.Icon />
          <span>{t('continueWith', { provider: p.name })}</span>
        </button>
      ))}
      {/* Under the buttons, above the "or" divider; the live region stays
          mounted so the note is announced when it appears. */}
      <div aria-live="polite">
        {soon && (
          <p data-tid="auth.coming-soon"
            className="flex items-start gap-2 rounded-lg bg-sky-50 px-3 py-2 text-sm text-slate-800">
            <Info size={16} aria-hidden="true" className="mt-0.5 shrink-0 text-sky-700" />
            <span>{t('comingSoon', { provider: soon })}</span>
          </p>
        )}
      </div>
    </div>
  )
}
