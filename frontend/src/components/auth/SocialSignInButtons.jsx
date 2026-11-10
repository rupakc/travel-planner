import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { getAuthProviders } from '../../services/api'
import { navigateTo } from './navigate'
import { AppleIcon, GoogleIcon, FacebookIcon, GitHubIcon } from './providerIcons'

// Brand names are not translated. Button colours follow each provider's
// published guidance, with the dark-theme variant they publish.
const PROVIDERS = [
  { id: 'apple', name: 'Apple', Icon: AppleIcon,
    cls: 'bg-black text-white border-black hover:bg-neutral-800 dark:bg-white dark:text-black dark:border-white dark:hover:bg-neutral-200' },
  { id: 'google', name: 'Google', Icon: GoogleIcon,
    cls: 'bg-white text-[#1f1f1f] border-[#747775] hover:bg-gray-50 dark:bg-[#131314] dark:text-[#e3e3e3] dark:border-[#8e918f] dark:hover:bg-[#1e1f20]' },
  { id: 'facebook', name: 'Facebook', Icon: FacebookIcon,
    cls: 'bg-[#1877F2] text-white border-[#1877F2] hover:bg-[#166fe5]' },
  { id: 'github', name: 'GitHub', Icon: GitHubIcon,
    cls: 'bg-[#24292f] text-white border-[#24292f] hover:bg-[#32383f] dark:bg-[#f6f8fa] dark:text-[#24292f] dark:border-[#d0d7de] dark:hover:bg-white' },
]

// Only a same-origin OAuth start path is ever navigated to.
const safeStart = (url) =>
  typeof url === 'string' && url.startsWith('/api/auth/') && !url.startsWith('//') ? url : null

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
      <p aria-live="polite" className="text-xs text-slate-500 dark:text-slate-400 min-h-[1rem]">
        {soon ? t('comingSoon', { provider: soon }) : ''}
      </p>
    </div>
  )
}
