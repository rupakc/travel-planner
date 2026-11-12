import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { patchSettings } from '../../services/accountApi'

export const GOAL_MIN = 1
export const GOAL_MAX = 250

// "How many countries do you want to see?" 1..250, saved to account settings.
export default function BucketGoalEditor({ token, goal = null, onSaved }) {
  const { t } = useTranslation('playYou')
  const [value, setValue] = useState(goal == null ? '' : String(goal))
  const [state, setState] = useState('idle') // idle | saving | saved | error
  const n = Number(value)
  const valid = value !== '' && Number.isInteger(n) && n >= GOAL_MIN && n <= GOAL_MAX

  async function save(e) {
    e.preventDefault()
    if (!valid || state === 'saving') return
    setState('saving')
    try {
      await patchSettings(token, { bucket_list_goal: n })
      setState('saved')
      onSaved?.(n)
    } catch {
      setState('error')
    }
  }

  return (
    <form onSubmit={save} className="rounded-2xl bg-white p-6 shadow" data-tid="play.goal.form" aria-labelledby="goal-title">
      <h2 id="goal-title" className="mb-1 text-lg font-semibold text-slate-800">{t('goal.title')}</h2>
      <p className="mb-3 text-sm text-slate-600">{t('goal.hint', { min: GOAL_MIN, max: GOAL_MAX })}</p>
      <div className="flex flex-wrap items-end gap-3">
        <label className="block text-sm font-medium text-slate-700">
          {t('goal.label')}
          <input type="number" inputMode="numeric" min={GOAL_MIN} max={GOAL_MAX} step="1" value={value}
            data-tid="play.goal.input" aria-invalid={value !== '' && !valid}
            onChange={(e) => { setValue(e.target.value); setState('idle') }}
            className="mt-1 block w-28 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-800" />
        </label>
        <button type="submit" disabled={!valid || state === 'saving'} data-tid="play.goal.save"
          className="min-h-[44px] rounded-lg bg-teal-700 px-4 py-2 text-sm font-semibold text-white hover:bg-teal-800 disabled:opacity-50">
          {t('goal.save')}
        </button>
      </div>
      {value !== '' && !valid && (
        <p role="alert" data-tid="play.goal.invalid" className="mt-2 text-sm text-red-700">{t('goal.invalid', { min: GOAL_MIN, max: GOAL_MAX })}</p>
      )}
      {state === 'saved' && <p role="status" data-tid="play.goal.saved" className="mt-2 text-sm text-emerald-700">{t('goal.saved')}</p>}
      {state === 'error' && <p role="alert" data-tid="play.goal.error" className="mt-2 text-sm text-red-700">{t('goal.error')}</p>}
    </form>
  )
}
