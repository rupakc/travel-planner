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
