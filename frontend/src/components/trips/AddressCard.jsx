import { useTranslation } from 'react-i18next'

// The hotel written large, with "Please take me to:" in the local script, to
// show a taxi driver.
export default function AddressCard({ card, language }) {
  const { t } = useTranslation('offlinePack')
  if (!card?.hotel_name) return null
  const phrase = card.take_me_to
  return (
    <section data-tid="offlinePack.address" className="rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 p-4">
      <h3 className="text-sm font-semibold text-gray-700 dark:text-gray-300 mb-2">{t('address.title')}</h3>
      <p lang={phrase?.text ? language : undefined} className="text-xl sm:text-2xl font-semibold text-gray-900 dark:text-gray-100 break-words" data-tid="offlinePack.address.phrase">
        {phrase?.text || t('address.fallback')}
      </p>
      {phrase?.romanized && <p className="text-sm text-gray-600 dark:text-gray-400 italic">{phrase.romanized}</p>}
      <p className="mt-3 text-2xl sm:text-3xl font-bold text-gray-900 dark:text-gray-100 break-words">{card.hotel_name}</p>
      {card.area && <p className="text-lg text-gray-800 dark:text-gray-200">{card.area}</p>}
      {card.city && <p className="text-lg text-gray-800 dark:text-gray-200">{card.city}</p>}
    </section>
  )
}
