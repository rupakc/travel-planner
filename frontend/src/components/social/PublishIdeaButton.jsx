import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useSocialEnabled } from '../../hooks/useSocial'
import PublishIdeaDialog from './PublishIdeaDialog'

/**
 * "Share to Ideas" entry point for a plan or recap. Renders nothing unless the
 * server has the social feed (`features.social`), so an older backend never shows it.
 */
export default function PublishIdeaButton({ kind, planId, className = '', tid }) {
  const { t } = useTranslation('socialShare')
  const { enabled } = useSocialEnabled()
  const [open, setOpen] = useState(false)
  if (!enabled || planId == null) return null
  return (
    <>
      <button type="button" onClick={() => setOpen(true)} data-tid={tid || `social.publish.open.${kind}`}
        className={className || 'min-h-[44px] rounded-lg border border-border px-4 text-sm font-medium text-text hover:bg-surface'}>
        {t('cta')}
      </button>
      {open && <PublishIdeaDialog kind={kind} planId={planId} onClose={() => setOpen(false)} />}
    </>
  )
}
