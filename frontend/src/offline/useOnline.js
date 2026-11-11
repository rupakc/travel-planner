// navigator.onLine, kept current through the online/offline events.
import { useEffect, useState } from 'react'

const current = () => {
  try { return typeof navigator === 'undefined' || navigator.onLine !== false } catch { return true }
}

export function useOnline() {
  const [online, setOnline] = useState(current)
  useEffect(() => {
    const update = () => setOnline(current())
    update()
    window.addEventListener('online', update)
    window.addEventListener('offline', update)
    return () => {
      window.removeEventListener('online', update)
      window.removeEventListener('offline', update)
    }
  }, [])
  return online
}
