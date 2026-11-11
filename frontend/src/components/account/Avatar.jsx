import { useEffect, useState } from 'react'
import { initials, avatarHue } from '../../utils/initials'

/** The user's picture; initials on a stable colour when there is none or it fails to load. */
export default function Avatar({ user, size = 32, className = '' }) {
  const url = user?.avatar_url || null
  const [broken, setBroken] = useState(false)
  useEffect(() => { setBroken(false) }, [url])
  const box = { width: size, height: size }
  if (url && !broken) {
    return (
      <img
        src={url}
        alt=""
        style={box}
        data-tid="avatar.image"
        onError={() => setBroken(true)}
        className={`rounded-full object-cover shrink-0 ${className}`}
      />
    )
  }
  const hue = avatarHue(user?.username)
  return (
    <span
      aria-hidden="true"
      data-tid="avatar.initials"
      style={{ ...box, fontSize: Math.max(10, Math.round(size * 0.4)), backgroundColor: `hsl(${hue} 55% 42%)` }}
      className={`inline-flex items-center justify-center rounded-full text-white font-semibold select-none shrink-0 ${className}`}
    >
      {initials(user?.display_name, user?.username)}
    </span>
  )
}
