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
    let sawDone = false

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
          if (parsed.type === 'done') sawDone = true
          self.postMessage(parsed)
        } catch (_) { /* skip malformed lines */ }
      }
    }
    // A stream that ends without the server's final `done` event was severed
    // mid-run (instance rollout, proxy drop, network blip) — the page must be
    // able to tell the difference so it can retry instead of leaving the
    // not-yet-arrived sections blank forever.
    self.postMessage({ type: sawDone ? '__stream_end' : '__interrupted' })
  } catch (err) {
    self.postMessage({ type: '__error', message: err.message })
  }
}
