import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { toAmountString } from '../../utils/money'

export const EXPENSE_CATEGORIES = ['flights', 'lodging', 'food', 'transport', 'activities', 'shopping', 'fees', 'other']

const field = 'w-full min-h-[44px] rounded-lg border border-slate-300 dark:border-slate-600 bg-white dark:bg-slate-800 px-3 text-sm text-slate-900 dark:text-slate-100'
const label = 'block text-xs font-medium text-slate-600 dark:text-slate-300 mb-1'

// Quick-add / edit form. onSubmit gets {amount, currency, category, note, spent_on}
// with a validated decimal-string amount; the caller does the saving.
export default function ExpenseForm({ initial, defaultCurrency, today, busy, onSubmit, onCancel }) {
  const { t } = useTranslation('expenses')
  const [amount, setAmount] = useState(initial?.amount ?? '')
  const [currency, setCurrency] = useState(initial?.currency ?? defaultCurrency)
  const [category, setCategory] = useState(initial?.category ?? 'food')
  const [note, setNote] = useState(initial?.note ?? '')
  const [day, setDay] = useState(initial?.spent_on ?? today)
  const [error, setError] = useState(null)

  const submit = (e) => {
    e.preventDefault()
    const cur = currency.trim().toUpperCase()
    if (!/^[A-Z]{3}$/.test(cur)) { setError(t('invalidCurrency')); return }
    const amt = toAmountString(amount, cur)
    if (!amt) { setError(t('invalidAmount')); return }
    setError(null)
    onSubmit({ amount: amt, currency: cur, category, note: note.trim(), spent_on: day || today })
  }

  return (
    <form onSubmit={submit} data-tid="expense-form" className="space-y-3">
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <div className="col-span-1">
          <label className={label} htmlFor="expense-amount">{t('amount')}</label>
          <input id="expense-amount" data-tid="expense-amount" className={field} inputMode="decimal"
            autoComplete="off" value={amount} onChange={(e) => setAmount(e.target.value)} />
        </div>
        <div className="col-span-1">
          <label className={label} htmlFor="expense-currency">{t('currency')}</label>
          <input id="expense-currency" data-tid="expense-currency" className={`${field} uppercase`} maxLength={3}
            autoComplete="off" value={currency} onChange={(e) => setCurrency(e.target.value)} />
        </div>
        <div className="col-span-2">
          <label className={label} htmlFor="expense-day">{t('day')}</label>
          <input id="expense-day" data-tid="expense-day" type="date" className={field}
            value={day} onChange={(e) => setDay(e.target.value)} />
        </div>
      </div>
      <div role="radiogroup" aria-label={t('category')} className="flex flex-wrap gap-2">
        {EXPENSE_CATEGORIES.map((c) => (
          <button key={c} type="button" role="radio" aria-checked={category === c} data-tid={`expense-cat-${c}`}
            onClick={() => setCategory(c)}
            className={`min-h-[44px] px-3 rounded-full text-sm border ${category === c
              ? 'bg-teal-700 border-teal-700 text-white'
              : 'bg-white dark:bg-slate-800 border-slate-300 dark:border-slate-600 text-slate-700 dark:text-slate-200'}`}>
            {t(`cat.${c}`)}
          </button>
        ))}
      </div>
      <div>
        <label className={label} htmlFor="expense-note">{t('note')}</label>
        <input id="expense-note" data-tid="expense-note" className={field} maxLength={140}
          value={note} onChange={(e) => setNote(e.target.value)} />
      </div>
      {error && <p role="alert" data-tid="expense-error" className="text-sm text-red-700 dark:text-red-300">{error}</p>}
      <div className="flex gap-2">
        <button type="submit" disabled={busy} data-tid="expense-save"
          className="min-h-[44px] px-4 rounded-lg bg-teal-700 hover:bg-teal-800 text-white text-sm font-medium disabled:opacity-60">
          {initial ? t('save') : t('add')}
        </button>
        {onCancel && (
          <button type="button" onClick={onCancel} data-tid="expense-cancel"
            className="min-h-[44px] px-4 rounded-lg border border-slate-300 dark:border-slate-600 text-sm text-slate-700 dark:text-slate-200">
            {t('cancel')}
          </button>
        )}
      </div>
    </form>
  )
}
