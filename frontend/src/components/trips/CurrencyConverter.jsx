import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { convert, roundFor, parseAmount, exponentFor } from '../../utils/converter'
import { fmtDate, fmtNumber } from '../../i18n/format'

const sameYear = (iso) => new Date(iso).getFullYear() === new Date().getFullYear()

// Offline converter. Honest labelling: the rate's date, and "approximate".
export default function CurrencyConverter({ currency }) {
  const { t } = useTranslation('offlinePack')
  const [amount, setAmount] = useState('')
  const [direction, setDirection] = useState('toLocal')
  if (!currency) return null
  const { local, home, rate, as_of: asOf, source } = currency
  if (rate == null) {
    return (
      <section data-tid="offlinePack.currency" className="rounded-xl border border-gray-200 bg-white p-4">
        <h3 className="text-sm font-semibold text-gray-700 mb-1">{t('currency.title')}</h3>
        <p data-tid="offlinePack.currency.norate" className="text-sm text-gray-600">{t('currency.noRate', { local })}</p>
      </section>
    )
  }
  const from = direction === 'toLocal' ? home : local
  const to = direction === 'toLocal' ? local : home
  const raw = amount === '' ? NaN : convert(parseAmount(amount), rate, direction)
  const out = Number.isFinite(raw) ? roundFor(to, raw) : null
  return (
    <section data-tid="offlinePack.currency" className="rounded-xl border border-gray-200 bg-white p-4">
      <h3 className="text-sm font-semibold text-gray-700 mb-2">{t('currency.title')}</h3>
      <div className="flex flex-wrap items-center gap-2">
        <input
          data-tid="offlinePack.currency.amount"
          inputMode="decimal"
          aria-label={t('currency.amountLabel', { currency: from })}
          value={amount}
          onChange={(e) => setAmount(e.target.value)}
          className="min-h-[44px] w-32 rounded-lg border border-gray-300 bg-white px-3 text-lg text-gray-900"
        />
        <span className="font-medium text-gray-800">{from}</span>
        <button
          type="button"
          data-tid="offlinePack.currency.swap"
          onClick={() => setDirection((d) => (d === 'toLocal' ? 'toHome' : 'toLocal'))}
          aria-label={t('currency.swap')}
          className="min-h-[44px] min-w-[44px] rounded-lg border border-gray-300 text-gray-800"
        >
          ⇄
        </button>
        <span data-tid="offlinePack.currency.result" className="text-lg font-semibold text-gray-900">
          {out == null ? '—' : fmtNumber(out, { minimumFractionDigits: 0, maximumFractionDigits: exponentFor(to) })} {to}
        </span>
      </div>
      <p className="mt-2 text-xs text-gray-600">
        {t('currency.rateFrom', {
          date: fmtDate(asOf, sameYear(asOf) ? { day: 'numeric', month: 'short' } : { day: 'numeric', month: 'short', year: 'numeric' }),
          source: t(`currency.sources.${source}`, { defaultValue: source || '' }),
        })}
      </p>
    </section>
  )
}
