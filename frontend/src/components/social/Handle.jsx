import { Link } from 'react-router-dom'
import { HANDLE_RE, profilePath } from './paths'

/** @handle as plain text; a link only when it is a well-formed handle (never trust server text in a URL). */
export default function Handle({ handle, className = '', tid = 'social.handle' }) {
  const text = `@${String(handle ?? '')}`
  if (!HANDLE_RE.test(String(handle ?? ''))) return <span className={className}>{text}</span>
  return (
    <Link to={profilePath(handle)} data-tid={tid} className={`font-medium hover:underline ${className}`}>{text}</Link>
  )
}
