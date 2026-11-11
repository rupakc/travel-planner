// Normalises any failed request into one shape, and turns it into UI text.
// Clients render text from `error_code` (the `errors` namespace) and fall back
// to the server's English `detail`.
function detailText(detail) {
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    const first = detail.find((d) => d && typeof d.msg === 'string')
    if (first) return first.msg
  }
  return ''
}

/** -> {status, code, detail, retryAfter, extra} */
export function toApiError(err) {
  const res = err?.response
  const body = res?.data && typeof res.data === 'object' ? res.data : {}
  const { detail, error_code: code, ...extra } = body
  const header = res?.headers?.['retry-after'] ?? res?.headers?.['Retry-After']
  const retry = Number.parseInt(header, 10)
  return {
    status: res?.status ?? 0,
    code: typeof code === 'string' && code ? code : null,
    detail: detailText(detail) || (res ? '' : err?.message || ''),
    retryAfter: Number.isFinite(retry) ? retry : null,
    extra,
  }
}

/** `errors:<code>` when that key exists, else the server's detail, else `errors:generic`. */
export function errorText(t, apiErr) {
  const code = apiErr?.code
  if (code) {
    const key = `errors:${code}`
    const text = t(key, { defaultValue: '' })
    // A missing key comes back as the key itself (without the namespace).
    if (text && text !== code && text !== key) return text
  }
  return apiErr?.detail || t('errors:generic')
}

/** Wraps a request promise: resolves with `data`, rejects with toApiError(err). */
export async function unwrap(promise) {
  try {
    return (await promise).data
  } catch (err) {
    throw toApiError(err)
  }
}
