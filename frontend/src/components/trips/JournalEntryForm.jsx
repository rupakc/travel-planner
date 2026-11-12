import { useState } from 'react'
import { useTranslation } from 'react-i18next'

export const MAX_BODY = 4000
export const MOODS = ['great', 'good', 'ok', 'tough']
const EMOJI = { great: '😄', good: '🙂', ok: '😐', tough: '😟' }

// New-entry form: text with a live counter (submit is blocked past 4000),
// optional mood and day. `days` is a list of {value, label}.
export default function JournalEntryForm({ onSubmit, days = [], busy = false }) {
  const { t } = useTranslation('journal')
  const [body, setBody] = useState('')
  const [mood, setMood] = useState(null)
  const [day, setDay] = useState('')
  const over = body.length > MAX_BODY
  const empty = !body.trim()

  const submit = async (e) => {
    e.preventDefault()
    if (over || empty || busy) return
    const ok = await onSubmit({ body: body.trim(), mood, day: day || null })
    if (ok) {
      setBody('')
      setMood(null)
    }
  }

  return (
    <form onSubmit={submit} className="space-y-3" data-tid="journal-form">
      <label className="block text-sm font-medium text-slate-700" htmlFor="journal-body">
        {t('form.label')}
      </label>
      <textarea
        id="journal-body"
        value={body}
        onChange={(e) => setBody(e.target.value)}
        rows={4}
        placeholder={t('form.placeholder')}
        aria-invalid={over}
        aria-describedby="journal-count"
        data-tid="journal-body"
        className="w-full rounded-lg border border-slate-300 bg-white p-3 text-base text-slate-900"
      />
      <div
        id="journal-count"
        data-tid="journal-counter"
        role={over ? 'alert' : undefined}
        className={`text-sm ${over ? 'text-red-700' : 'text-slate-600'}`}
      >
        {over ? t('form.tooLong', { n: body.length, max: MAX_BODY }) : t('form.counter', { n: body.length, max: MAX_BODY })}
      </div>
      <div role="radiogroup" aria-label={t('mood.group')} className="flex flex-wrap gap-2">
        {MOODS.map((m) => (
          <button
            key={m}
            type="button"
            role="radio"
            aria-checked={mood === m}
            onClick={() => setMood(mood === m ? null : m)}
            data-tid={`journal-mood-${m}`}
            className={`min-h-[44px] rounded-full border px-3 text-sm ${mood === m
              ? 'border-teal-700 bg-teal-50 text-teal-900'
              : 'border-slate-300 text-slate-700'}`}
          >
            <span aria-hidden="true">{EMOJI[m]} </span>{t(`mood.${m}`)}
          </button>
        ))}
      </div>
      {days.length > 0 && (
        <label className="block text-sm text-slate-700">
          {t('form.day')}
          <select
            value={day}
            onChange={(e) => setDay(e.target.value)}
            data-tid="journal-day"
            className="mt-1 block min-h-[44px] w-full rounded-lg border border-slate-300 bg-white px-2 text-slate-900"
          >
            <option value="">{t('form.noDay')}</option>
            {days.map((d) => <option key={d.value} value={d.value}>{d.label}</option>)}
          </select>
        </label>
      )}
      <button
        type="submit"
        disabled={over || empty || busy}
        data-tid="journal-add"
        className="min-h-[44px] rounded-lg bg-teal-700 px-4 text-white hover:bg-teal-800 disabled:opacity-50"
      >
        {t('form.add')}
      </button>
    </form>
  )
}
