import { useEffect, useRef, useState } from 'react'
import QuizRunner from './QuizRunner'
import QuizResult from './QuizResult'
import { emit } from '../../telemetry/client'

// One quiz from first question to result. `mode` is the telemetry mode
// (daily, pack, challenge, h2h); `onClose` goes back to the hub.
export default function QuizPlayer({ token, session, mode, pack, onClose, onSummary }) {
  const [summary, setSummary] = useState(session.done ? session.summary : null)
  const started = useRef(false)
  useEffect(() => {
    if (started.current) return
    started.current = true
    emit('play_quiz_start', { mode, pack: pack || 'none' })
  }, [mode, pack])

  function done(s) {
    setSummary(s)
    emit('play_quiz_done', { mode, correct: s?.correct ?? 0 })
    onSummary?.(s)
  }
  if (summary) return <QuizResult summary={summary} sessionId={session.session_id} onClose={onClose} />
  return <QuizRunner token={token} session={session} onDone={done} />
}
