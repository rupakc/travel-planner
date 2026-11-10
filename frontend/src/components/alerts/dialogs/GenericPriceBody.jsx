import { Trans, useTranslation } from 'react-i18next'
import { formatPrice } from '../../../utils/priceWatch'

/**
 * Default body of the price-watch dialog. Every body gets
 * `{ kind, spec, preview, watch, unitLabel }`: `spec` is the spec actually
 * sent (a picked suggestion's, after a no-live-price answer), `preview` what
 * the page already knows ({ title, subtitle, price, priceLabel, currency }),
 * `watch` the created watch once there is one (show the matched subject so
 * the traveller sees what is tracked), and `unitLabel` the kind's wording
 * after a unit price ("per night", "per person").
 */
export default function GenericPriceBody({ preview = {}, watch = null, unitLabel = null }) {
  const { t } = useTranslation('alerts')
  if (watch) {
    const unit = watch.last_observation?.unit_price
    return (
      <p className="text-sm text-slate-600">
        <Trans t={t} i18nKey="body.tracking" values={{ title: watch.title }}
          components={{ strong: <strong className="text-slate-800" /> }} />
        {watch.subtitle ? ` · ${watch.subtitle}` : ''}
        {unit != null ? ` · ${formatPrice(unit, watch.currency)} ${unitLabel || t('unit.unit')}` : ''}
      </p>
    )
  }
  if (preview.price == null) return null
  return (
    <div className="mt-3 rounded-xl bg-slate-50 px-4 py-3">
      <p className="text-sm text-slate-600">
        {t('body.shownNow')} <span className="text-2xl font-semibold tabular-nums text-slate-900">{formatPrice(preview.price, preview.currency)}</span>
        {(preview.priceLabel || unitLabel) && <span className="ml-1.5 text-xs text-slate-500">{preview.priceLabel || unitLabel}</span>}
      </p>
      <p className="mt-1 text-xs text-slate-500">{t('body.lookupLater')}</p>
    </div>
  )
}
