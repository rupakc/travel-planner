// SSE Web Worker — parses the event stream off the main thread
self.onmessage = async ({ data: { url, body, headers } }) => {
  try {
    const response = await fetch(url, { method: 'POST', headers, body })
    if (!response.ok) {
      self.postMessage({ type: '__error', message: `HTTP ${response.status}` })
      return
    }
    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''

    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split('\n')
      buffer = lines.pop()
      for (const line of lines) {
        if (!line.startsWith('data: ')) continue   // skip keepalive comments
        try {
          const parsed = JSON.parse(line.slice(6))
          self.postMessage(parsed)
        } catch (_) { /* skip malformed lines */ }
      }
    }
    self.postMessage({ type: '__stream_end' })
  } catch (err) {
    self.postMessage({ type: '__error', message: err.message })
  }
}
