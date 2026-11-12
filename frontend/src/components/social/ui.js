import { errorText } from '../../services/apiError'

// Shared class strings (theme tokens only).
export const btn = 'min-h-[44px] rounded-lg border border-border px-3 text-sm font-medium text-text hover:bg-surface disabled:opacity-60'
export const btnPrimary = 'min-h-[44px] rounded-lg bg-teal-700 px-4 text-sm font-medium text-white hover:bg-teal-800 disabled:opacity-60'
export const field = 'min-h-[44px] w-full rounded-lg border border-border bg-surface-raised px-3 text-sm text-text'
export const card = 'rounded-2xl border border-border bg-surface-raised p-4 shadow-sm'

/** `<ns>:errors.<code>` when the namespace has it, else the shared error text. `t` is bound to that namespace. */
export function socialError(t, apiErr) {
  const code = apiErr?.code
  if (code) {
    const text = t(`errors.${code}`, { defaultValue: '' })
    if (text) return text
  }
  return errorText(t, apiErr)
}
