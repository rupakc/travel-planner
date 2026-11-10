import { useMemo, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { BellPlus, BellRing } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import i18n from '../../i18n'
import { useOptionalAuth } from '../../context/AuthContext'
import { useAlerts, usePriceWatchFor } from '../../context/AlertsContext'
import { hotelPreview, hotelWatchSpec } from '../../utils/hotelWatch'
import { formatPrice, priceWatchLink } from '../../utils/priceWatch'
import { loginPathFor } from '../../utils/returnPath'
import { useAirportCities } from '../../hooks/useAirportCities'
import { withCityNames } from '../../utils/cityNames'
import PriceWatchDialog from './PriceWatchDialog'

const STYLES = {
  // small text action on a hotel card or in the My Plan drawer
  inline: {
    idle: 'inline-flex min-h-6 items-center gap-1 rounded py-1 text-xs font-medium text-sky-700 hover:text-sky-900 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-sky-500',
    on: 'inline-flex min-h-6 items-center gap-1 rounded py-1 text-xs font-medium text-emerald-700 hover:text-emerald-900 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-sky-500',
    size: 12,
  },
  // the compact chat cards
  compact: {
    idle: 'inline-flex min-h-6 items-center gap-0.5 rounded py-1 text-[10px] font-medium text-sky-700 hover:text-sky-900 focus-visible:outline focus-visible:outline-2 focus-visible:outline-sky-500',
    on: 'inline-flex min-h-6 items-center gap-0.5 rounded py-1 text-[10px] font-medium text-emerald-700 hover:text-emerald-900 focus-visible:outline focus-visible:outline-2 focus-visible:outline-sky-500',
    size: 9,
  },
}

export const hotelWatchingLabel = (w) => {
  if (w.status === 'paused') return i18n.t('alerts:btn.watchPaused')
  if (w.status === 'error') return i18n.t('alerts:btn.watchHold')
  return w.last_price != null
    ? i18n.t('alerts:btn.watchingPrice', { price: formatPrice(w.last_price, w.currency) })
    : i18n.t('alerts:btn.watching')
}

/**
 * "Watch price" on a hotel. Needs the stay's dates (from the search: check-in
 * on departure, check-out on return, or the city's nights on a multi-city
 * trip) and live prices on the server; otherwise renders nothing. Signed out
 * it leads to sign-in and back; once watched it reads "Watching · $398" and
 * opens that watch on the Alerts page.
 */
export default function WatchHotelButton({ hotel, searchData, variant = 'inline', source = 'results' }) {
  const { token } = useOptionalAuth()
  const { caps } = useAlerts()
  // the search stores airport codes ("LIS"): watch the city ("Lisbon")
  const name = useAirportCities([searchData?.destination, ...(searchData?.destinations || []), hotel?.city])
  const spec = useMemo(() => name && hotelWatchSpec(
    hotel?.city ? { ...hotel, city: name(hotel.city) } : hotel, withCityNames(searchData, name),
  ), [hotel, searchData, name])
  if (!caps.fareWatch || !spec) return null
  if (!token) return <SignInToWatch hotel={hotel} variant={variant} />
  return <ActiveHotelButton hotel={hotel} spec={spec} variant={variant} source={source} />
}

function SignInToWatch({ hotel, variant }) {
  const { t } = useTranslation('alerts')
  const navigate = useNavigate()
  const location = useLocation()
  const style = STYLES[variant] || STYLES.inline
  return (
    <button type="button" data-tid="alerts.watch-hotel-signin" className={style.idle} title={t('btn.signInHotel')}
      aria-label={t('btn.signInHotelAria', { name: hotel.name })}
      onClick={(e) => { e.stopPropagation(); navigate(loginPathFor(location)) }}>
      <BellPlus size={style.size} aria-hidden="true" /> {t('btn.watchPrice')}
    </button>
  )
}

function ActiveHotelButton({ hotel, spec, variant, source }) {
  const { t } = useTranslation('alerts')
  const navigate = useNavigate()
  const [open, setOpen] = useState(false)
  const [watch, setWatch] = usePriceWatchFor('hotel', spec)
  const style = STYLES[variant] || STYLES.inline
  const watching = watch && watch.status !== 'expired'

  const onClick = (e) => {
    e.stopPropagation()
    if (watching) navigate(priceWatchLink(watch))
    else setOpen(true)
  }
  // A picked suggestion is a different hotel: this card's own hotel stays unwatched
  const onWatched = (w, meta) => { if (!meta?.viaSuggestion) setWatch(w) }

  return (
    <>
      <button type="button" data-tid="alerts.watch-hotel" onClick={onClick} className={watching ? style.on : style.idle}
        aria-label={watching ? t('btn.openAriaNamed', { label: hotelWatchingLabel(watch), name: hotel.name }) : t('btn.watchHotelAria', { name: hotel.name })}
        title={watching ? t('btn.openWatch') : t('btn.hotelTitle')}>
        {watching ? <BellRing size={style.size} aria-hidden="true" /> : <BellPlus size={style.size} aria-hidden="true" />}
        <span className="tabular-nums">{watching ? hotelWatchingLabel(watch) : t('btn.watchPrice')}</span>
      </button>
      {open && (
        // Clicks inside the (portalled) dialog must not reach the card's own onClick
        <span onClick={e => e.stopPropagation()}>
          <PriceWatchDialog kind="hotel" spec={spec} preview={hotelPreview(hotel, spec)} unitLabel={t('unit.night')} source={source}
            onClose={() => setOpen(false)} onWatched={onWatched} />
        </span>
      )}
    </>
  )
}
