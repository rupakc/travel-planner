// Error text for failed requests on the legacy paths (fetch Responses, the
// old axios client, the SSE workers). Contract: clients render text from
// `error_code` (the `errors` namespace) and fall back to the server's string
// `detail` — so a translated AI-gate refusal (email_unverified,
// ai_daily_quota, …) shows in the UI language, and the old window-limit 429s,
// which carry no code, still show their `detail` as-is.
//
// This module is also bundled into the SSE workers, which have no i18n: the
// main thread registers the translator (i18n/index.js), the workers post the
// code, and the page translates it with errorCodeText().

let translate = null

/** Registers `(key, options) => string` used to translate `errors:<code>`. */
export function setErrorTranslator(fn) {
  translate = typeof fn === 'function' ? fn : null
}

/** The translation of `errors:<code>`, or null when there is no such key (or no translator). */
export function errorCodeText(code) {
  if (!translate || typeof code !== 'string' || !code) return null
  try {
    const key = `errors:${code}`
    const text = translate(key, { defaultValue: '' })
    // i18next hands back the key (without the namespace) for a missing one.
    return typeof text === 'string' && text && text !== code && text !== key ? text : null
  } catch {
    return null
  }
}

const stringDetail = (detail) => (typeof detail === 'string' && detail.trim() ? detail.trim() : null)
const codeOf = (body) => (body && typeof body === 'object' && typeof body.error_code === 'string' && body.error_code ? body.error_code : null)

/**
 * `{status, code, detail}` for a failed fetch Response; `code`/`detail` are
 * null when absent. Never throws (a non-JSON body gives nulls).
 * @param {Response} response
 */
export async function responseErrorInfo(response) {
  let body = null
  try { body = await response.json() } catch { /* not JSON */ }
  return { status: response.status, code: codeOf(body), detail: stringDetail(body?.detail) }
}

/**
 * Human message for a failed fetch Response: the translated `error_code` when
 * one exists, else the API's string `detail` (e.g. the 429 "Too many requests
 * — please wait N seconds…"), otherwise `fallback` (default "HTTP <status>").
 * Never raw JSON.
 * @param {Response} response
 * @param {string|null} [fallback]
 */
export async function responseErrorMessage(response, fallback = `HTTP ${response.status}`) {
  const { code, detail } = await responseErrorInfo(response)
  return errorCodeText(code) || detail || fallback
}

/**
 * The API's message and HTTP status from an axios error: `detail` is the
 * translated `error_code` when it has a translation, else the server's
 * non-blank string detail, else null; `status` is null when there was no
 * response (network error).
 * @param {unknown} err
 * @returns {{ detail: string|null, status: number|null }}
 */
export function axiosErrorDetail(err) {
  const res = err && typeof err === 'object' ? err.response : null
  return {
    detail: errorCodeText(codeOf(res?.data)) || stringDetail(res?.data?.detail),
    status: typeof res?.status === 'number' ? res.status : null,
  }
}
