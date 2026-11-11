// A small, dependency-free strength heuristic for the sign-up / reset meters.
// It is advice only: the server's password rules (length, common list, identity
// match) are the authority. Returns {score: 0..4, hints: string[]}; hint values
// are `signup:strength.hint.*` key suffixes.

const hasSequence = (s) => {
  const lower = s.toLowerCase()
  for (let i = 0; i + 3 < lower.length; i += 1) {
    const [a, b, c, d] = [0, 1, 2, 3].map((k) => lower.charCodeAt(i + k))
    if ((b - a === 1 && c - b === 1 && d - c === 1) || (a - b === 1 && b - c === 1 && c - d === 1)) return true
  }
  return false
}

// The server's minimum (core/passwords MIN_PASSWORD_LENGTH_V2, /config
// auth.min_password_length) for sign-up, reset, change-password and admin-set
// passwords. Older backends accepted 8, so 10 is safe against both.
export const MIN_PASSWORD_LENGTH = 10
const MIN_LENGTH = MIN_PASSWORD_LENGTH

const identityParts = ({ username, email } = {}) => {
  const parts = [username, typeof email === 'string' ? email.split('@')[0] : '']
  return parts.map((p) => String(p || '').toLowerCase()).filter((p) => p.length >= 3)
}

export function passwordStrength(pw, { username, email } = {}) {
  const password = typeof pw === 'string' ? pw : ''
  if (!password) return { score: 0, hints: [] }
  const hints = []
  const len = [...password].length

  let score = len < MIN_LENGTH ? 0 : len < 12 ? 1 : len < 16 ? 2 : 3
  if (len < MIN_LENGTH) hints.push('tooShort')
  else if (len < 16) hints.push('longer')

  const classes = [/[a-z]/, /[A-Z]/, /\d/, /[^a-zA-Z0-9]/].filter((re) => re.test(password)).length
  if (len >= MIN_LENGTH && (classes >= 3 || len >= 20)) score += 1
  if (classes < 3 && len < 20) hints.push('variety')

  const distinct = new Set(password).size
  const repeated = /(.)\1{2,}/.test(password) || distinct * 3 < len
  if (repeated) { score -= 1; hints.push('repeats') }
  if (distinct * 3 < len) score = Math.min(score, 0)
  if (hasSequence(password)) { score -= 1; hints.push('sequence') }

  const lower = password.toLowerCase()
  if (identityParts({ username, email }).some((p) => lower.includes(p))) {
    score -= 2
    hints.push('identity')
  }
  return { score: Math.max(0, Math.min(4, score)), hints }
}
