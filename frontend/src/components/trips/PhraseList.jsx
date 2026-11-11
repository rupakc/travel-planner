import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'

// Useful phrases in the local language, with a romanisation line and a
// full-screen "Show" view to hold up to someone.
export default function PhraseList({ phrases }) {
  const { t } = useTranslation('offlinePack')
  const [shown, setShown] = useState(null)
  const closeRef = useRef(null)
  useEffect(() => {
    if (!shown) return undefined
    closeRef.current?.focus()
    const onKey = (e) => { if (e.key === 'Escape') setShown(null) }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [shown])
  if (!phrases?.items?.length) return null
  return (
    <section data-tid="offlinePack.phrases" className="rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 p-4">
      <h3 className="text-sm font-semibold text-gray-700 dark:text-gray-300 mb-2">
        {t('phrases.title', { language: phrases.language_name || phrases.language })}
      </h3>
      <ul className="divide-y divide-gray-100 dark:divide-gray-800">
        {phrases.items.map((p) => (
          <li key={p.id} className="py-2 flex items-center gap-3">
            <div className="min-w-0 flex-1">
              <p className="text-xs text-gray-600 dark:text-gray-400">{t(`phrases.ids.${p.id}`, { defaultValue: p.id })}</p>
              <p className="text-lg text-gray-900 dark:text-gray-100 break-words">{p.text}</p>
              {p.romanized && <p className="text-sm italic text-gray-600 dark:text-gray-400">{p.romanized}</p>}
            </div>
            <button
              type="button"
              data-tid={`offlinePack.phrase.show.${p.id}`}
              onClick={() => setShown(p)}
              className="min-h-[44px] min-w-[44px] px-3 rounded-lg border border-teal-700 text-teal-800 dark:text-teal-300 dark:border-teal-500 text-sm font-medium"
            >
              {t('phrases.show')}
            </button>
          </li>
        ))}
      </ul>
      {shown && (
        <div
          role="dialog"
          aria-modal="true"
          aria-label={t(`phrases.ids.${shown.id}`, { defaultValue: shown.id })}
          data-tid="offlinePack.phrase.full"
          className="fixed inset-0 z-[60] flex flex-col items-center justify-center gap-4 bg-white dark:bg-gray-950 p-6 text-center"
        >
          <p className="text-4xl sm:text-6xl font-bold text-gray-900 dark:text-gray-100 break-words max-w-full">{shown.text}</p>
          {shown.romanized && <p className="text-xl sm:text-2xl italic text-gray-700 dark:text-gray-300">{shown.romanized}</p>}
          <button
            ref={closeRef}
            type="button"
            data-tid="offlinePack.phrase.close"
            onClick={() => setShown(null)}
            className="min-h-[44px] px-6 rounded-lg bg-teal-700 hover:bg-teal-800 text-white font-medium"
          >
            {t('phrases.close')}
          </button>
        </div>
      )}
    </section>
  )
}
