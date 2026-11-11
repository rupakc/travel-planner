import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { convert, roundFor } from '../../utils/converter'
import { fmtDate, fmtNumber } from '../../i18n/format'

// Offline converter. Honest labelling: the rate's date, and "approximate".
export default function CurrencyConverter({ currency }) {
  const { t } = useTranslation('offlinePack')
  const [amount, setAmount] = useState('')
  const [direction, setDirection] = useState('toLocal')
  if (!currency) return null
  const { local, home, rate, as_of: asOf } = currency
  if (rate == null) {
    return (
      <section data-tid="offlinePack.currency" className="rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 p-4">
        <h3 className="text-sm font-semibold text-gray-700 dark:text-gray-300 mb-1">{t('currency.title')}</h3>
        <p data-tid="offlinePack.currency.norate" className="text-sm text-gray-600 dark:text-gray-400">{t('currency.noRate', { local })}</p>
      </section>
    )
  }
  const from = direction === 'toLocal' ? home : local
  const to = direction === 'toLocal' ? local : home
  const raw = amount === '' ? NaN : convert(amount.replace(',', '.'), rate, direction)
  const out = Number.isFinite(raw) ? roundFor(to, raw) : null
  const digits = to && roundFor(to, 1.23456) === 1 ? 0 : undefined
  return (
    <section data-tid="offlinePack.currency" className="rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 p-4">
      <h3 className="text-sm font-semibold text-gray-700 dark:text-gray-300 mb-2">{t('currency.title')}</h3>
      <div className="flex flex-wrap items-center gap-2">
        <input
          data-tid="offlinePack.currency.amount"
          inputMode="decimal"
          aria-label={t('currency.amountLabel', { currency: from })}
          value={amount}
          onChange={(e) => setAmount(e.target.value)}
          className="min-h-[44px] w-32 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 px-3 text-lg text-gray-900 dark:text-gray-100"
        />
        <span className="font-medium text-gray-800 dark:text-gray-200">{from}</span>
        <button
          type="button"
          data-tid="offlinePack.currency.swap"
          onClick={() => setDirection((d) => (d === 'toLocal' ? 'toHome' : 'toLocal'))}
          aria-label={t('currency.swap')}
          className="min-h-[44px] min-w-[44px] rounded-lg border border-gray-300 dark:border-gray-600 text-gray-800 dark:text-gray-200"
        >
          ⇄
        </button>
        <span data-tid="offlinePack.currency.result" className="text-lg font-semibold text-gray-900 dark:text-gray-100">
          {out == null ? '—' : fmtNumber(out, digits === 0 ? { maximumFractionDigits: 0 } : { minimumFractionDigits: 0, maximumFractionDigits: 3 })} {to}
        </span>
      </div>
      <p className="mt-2 text-xs text-gray-600 dark:text-gray-400">
        {t('currency.rateFrom', { date: fmtDate(asOf, { day: 'numeric', month: 'short' }) })}
      </p>
    </section>
  )
}
