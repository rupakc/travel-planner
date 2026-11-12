import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { answerQuiz } from '../../services/playApi'
import { toApiError, errorText } from '../../services/apiError'
import { emit } from '../../telemetry/client'
import { optionLabel, promptText } from './quizText'

export const QUESTION_SECONDS = 15

// Plays one quiz session: question, big options, a display-only countdown
// (the server times every answer), a reveal, then the next question.
// `onDone(summary)` gets the session summary after the last answer.
export default function QuizRunner({ token, session, onDone }) {
  const { t, i18n } = useTranslation('play')
  const questions = session.questions || []
  const answered = new Map((session.answers || []).map((a) => [a.index, a]))
  const firstOpen = questions.findIndex((q) => !answered.has(q.index))
  const [pos, setPos] = useState(firstOpen < 0 ? questions.length - 1 : firstOpen)
  const [reveal, setReveal] = useState(null) // {choice, correct, correct_choice, points}
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [seconds, setSeconds] = useState(0)
  const summary = useRef(null)
  const q = questions[pos]

  useEffect(() => {
    if (reveal) return undefined
    setSeconds(0)
    const id = setInterval(() => setSeconds((s) => s + 1), 1000)
    return () => clearInterval(id)
  }, [pos, reveal])

  if (!q) return null
  const left = Math.max(0, QUESTION_SECONDS - seconds)
  const last = pos >= questions.length - 1

  async function pick(opt) {
    if (busy || reveal) return
    setBusy(true); setError('')
    try {
      const r = await answerQuiz(token, session.session_id, q.index, opt.id)
      emit('play_quiz_answer', { correct: !!r.correct, elapsed_s: Math.max(0, Math.round((r.elapsed_ms || 0) / 1000)) })
      setReveal({ choice: opt.id, correct: !!r.correct, correct_choice: r.correct_choice, points: r.points || 0 })
      if (r.done) summary.current = r.summary || {}
    } catch (e) {
      setError(errorText(t, e?.status !== undefined ? e : toApiError(e)))
    } finally {
      setBusy(false)
    }
  }

  function next() {
    if (summary.current) { onDone(summary.current); return }
    setReveal(null)
    setPos((p) => p + 1)
  }

  const label = promptText(t, q.prompt, i18n.language)
  return (
    <section className="rounded-2xl bg-white p-4 shadow sm:p-6" data-tid="play.quiz" aria-labelledby="quiz-q">
      <div className="mb-3 flex items-center justify-between text-sm text-slate-600">
        <span data-tid="play.quiz.progress">{t('quiz.progress', { current: pos + 1, total: questions.length })}</span>
        <span data-tid="play.quiz.timer" role="timer" aria-live="off">{t('quiz.timer', { count: left })}</span>
      </div>
      <div className="mb-4 h-2 overflow-hidden rounded-full bg-slate-200" aria-hidden="true">
        <div className="h-full rounded-full bg-teal-600 transition-[width] duration-1000 ease-linear motion-reduce:transition-none"
          style={{ width: `${reveal ? 0 : (left / QUESTION_SECONDS) * 100}%` }} />
      </div>
      {q.prompt?.template === 'flag' && (
        <p className="text-center text-7xl" data-tid="play.quiz.flag" role="img" aria-label={t('quiz.flagAlt')}>{q.prompt.flag}</p>
      )}
      <h2 id="quiz-q" className="my-4 text-center text-xl font-semibold text-slate-800" data-tid="play.quiz.prompt">{label}</h2>
      <ul className="grid gap-3">
        {q.options.map((opt) => {
          const isRight = reveal && reveal.correct_choice === opt.id
          const isWrong = reveal && reveal.choice === opt.id && !reveal.correct
          const tone = isRight ? 'border-emerald-600 bg-emerald-50 text-emerald-900'
            : isWrong ? 'border-rose-600 bg-rose-50 text-rose-900'
              : 'border-slate-300 bg-white text-slate-800 hover:border-teal-600'
          return (
            <li key={opt.id}>
              <button type="button" disabled={busy || !!reveal} onClick={() => pick(opt)}
                data-tid={`play.quiz.option.${opt.id}`}
                className={`min-h-[56px] w-full rounded-xl border-2 px-4 py-3 text-left text-base font-medium transition-colors motion-reduce:transition-none ${tone}`}>
                {optionLabel(opt, i18n.language)}
                {isRight && <span className="sr-only"> {t('quiz.correct')}</span>}
                {isWrong && <span className="sr-only"> {t('quiz.wrong')}</span>}
              </button>
            </li>
          )
        })}
      </ul>
      {error && <p role="alert" data-tid="play.quiz.error" className="mt-3 text-sm text-rose-700">{error}</p>}
      {reveal && (
        <div className="mt-4 flex flex-wrap items-center justify-between gap-3" role="status" data-tid="play.quiz.reveal">
          <p className="font-semibold text-slate-800">
            {reveal.correct ? t('quiz.correctPoints', { count: reveal.points }) : t('quiz.wrongNote')}
          </p>
          <button type="button" onClick={next} data-tid="play.quiz.next"
            className="min-h-[44px] rounded-lg bg-teal-700 px-5 py-2 text-sm font-semibold text-white">
            {last ? t('quiz.finish') : t('quiz.next')}
          </button>
        </div>
      )}
    </section>
  )
}
