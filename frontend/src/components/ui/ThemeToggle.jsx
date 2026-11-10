import { useTranslation } from 'react-i18next'
import { Sun, Moon, Monitor } from 'lucide-react'
import { useTheme } from '../../theme/ThemeContext'

// One button that cycles light (the default) → dark → system.
const NEXT = { light: 'dark', dark: 'system', system: 'light' }
const ICONS = { light: Sun, dark: Moon, system: Monitor }

// Resolved at call time and never awaited, so telemetry can't slow the click.
const report = (event, props) => {
  import('../../telemetry/client').then((m) => m.emit(event, props)).catch(() => {})
}

export default function ThemeToggle({ className = '' }) {
  const { t } = useTranslation('common')
  const { theme, setTheme } = useTheme()
  const mode = ICONS[theme] ? theme : 'light'
  const Icon = ICONS[mode]
  const label = t('theme.current', { mode: t(`theme.${mode}`) })

  const onClick = () => {
    const to = NEXT[mode]
    setTheme(to)
    report('theme_change', { theme: to })
  }

  return (
    <button
      type="button"
      data-tid="nav.theme"
      onClick={onClick}
      aria-label={label}
      title={label}
      className={`rounded-md p-1.5 text-slate-500 transition-colors hover:bg-slate-100 hover:text-slate-700 ${className}`}
    >
      <Icon size={14} aria-hidden="true" />
    </button>
  )
}
