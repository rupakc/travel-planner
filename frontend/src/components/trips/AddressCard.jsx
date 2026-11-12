import { useTranslation } from 'react-i18next'

// The hotel written large, with "Please take me to:" in the local script, to
// show a taxi driver.
export default function AddressCard({ card, language }) {
  const { t } = useTranslation('offlinePack')
  if (!card?.hotel_name) return null
  const phrase = card.take_me_to
  return (
    <section data-tid="offlinePack.address" className="rounded-xl border border-gray-200 bg-white p-4">
      <h3 className="text-sm font-semibold text-gray-700 mb-2">{t('address.title')}</h3>
      <p lang={phrase?.text ? language : undefined} className="text-xl sm:text-2xl font-semibold text-gray-900 break-words" data-tid="offlinePack.address.phrase">
        {phrase?.text || t('address.fallback')}
      </p>
      {phrase?.romanized && <p className="text-sm text-gray-600 italic">{phrase.romanized}</p>}
      <p className="mt-3 text-2xl sm:text-3xl font-bold text-gray-900 break-words">{card.hotel_name}</p>
      {card.area && <p className="text-lg text-gray-800">{card.area}</p>}
      {card.city && <p className="text-lg text-gray-800">{card.city}</p>}
    </section>
  )
}
