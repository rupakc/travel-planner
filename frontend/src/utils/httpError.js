/**
 * Human message for a failed fetch Response: the API's string `detail`
 * (e.g. the 429 "Too many requests — please wait N seconds…") when there is
 * one, otherwise `fallback` (default "HTTP <status>"). Never raw JSON.
 * @param {Response} response
 * @param {string|null} [fallback]
 */
export async function responseErrorMessage(response, fallback = `HTTP ${response.status}`) {
  try {
    const detail = (await response.json())?.detail
    if (typeof detail === 'string' && detail.trim()) return detail.trim()
  } catch {
    /* not JSON */
  }
  return fallback
}

/**
 * The API's string `detail` and HTTP status from an axios error; `detail` is
 * null unless the server sent a non-blank string, `status` null when there
 * was no response (network error).
 * @param {unknown} err
 * @returns {{ detail: string|null, status: number|null }}
 */
export function axiosErrorDetail(err) {
  const res = err && typeof err === 'object' ? err.response : null
  const detail = res?.data?.detail
  return {
    detail: typeof detail === 'string' && detail.trim() ? detail.trim() : null,
    status: typeof res?.status === 'number' ? res.status : null,
  }
}
