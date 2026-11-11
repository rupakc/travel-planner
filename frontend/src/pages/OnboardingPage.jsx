// The shared 5-step onboarding (same keys, order and copy as Android and iOS):
// 1 welcome → 2 how you travel (six questions, then the traveller type) →
// 3 home airport + passport → 4 notifications → 5 first trip or explore.
//
// Every step reports itself with PUT /account/onboarding {step, done: false}
// (fire-and-forget), so the page resumes from `onboarding.step` on any
// device. Answers stay on this device in localStorage tp_quiz_<user_id>.
// Finishing merges the answers into the server Preferences (read-modify-
// write) and marks onboarding done with the traveller type; skipping marks it
// done and skipped. Full screen, outside the Layout; only with the journey on.
import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { useJourney } from '../hooks/useJourney'
import { useAuth } from '../context/AuthContext'
import { getAccount, putOnboarding } from '../services/accountApi'
import { announceGame } from '../game/announce'
import { emit } from '../telemetry/client'
import { QUESTIONS, classify } from '../utils/travellerQuiz'
import {
  mergeQuizAnswers, loadQuizAnswers, saveQuizAnswers, loadHomeAirport, saveHomeAirport,
} from '../utils/quizPreferences'
import OnboardingProgress from '../components/onboarding/OnboardingProgress'
import QuizStep, { primaryBtn, secondaryBtn } from '../components/onboarding/QuizStep'
import TravellerTypeResult from '../components/onboarding/TravellerTypeResult'
import HomePassportStep from '../components/onboarding/HomePassportStep'
import NotificationsStep, { notificationsSupported } from '../components/onboarding/NotificationsStep'
import FirstTripStep from '../components/onboarding/FirstTripStep'
import { markOnboardingSeen } from '../components/onboarding/OnboardingGate'

const STEPS = 5
const RESULT = QUESTIONS.length // question index of the result screen

// Fire-and-forget: never blocks or breaks the flow.
function quietly(fn) {
  try { Promise.resolve(fn()).catch(() => {}) } catch { /* ignored */ }
}

async function preferencesRequest(token, body) {
  const res = await fetch('/api/preferences', body === undefined
    ? { headers: { Authorization: `Bearer ${token}` } }
    : {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify(body),
      })
  if (!res.ok) {
    const data = await res.json().catch(() => ({}))
    throw new Error(typeof data?.detail === 'string' ? data.detail : '')
  }
  return res.json()
}

export default function OnboardingPage() {
  const { t } = useTranslation('onboarding')
  const navigate = useNavigate()
  const { enabled, loaded } = useJourney()
  const { token, user, preferences, refreshPreferences } = useAuth()
  const userId = user?.id || user?.username || null

  const [canNotify] = useState(notificationsSupported)
  const [step, setStep] = useState(null) // null until /account answers
  const [resumed, setResumed] = useState(false)
  const [question, setQuestion] = useState(0)
  const [answers, setAnswers] = useState(() => loadQuizAnswers(userId))
  const [airport, setAirport] = useState(() => loadHomeAirport(userId))
  const [passport, setPassport] = useState(preferences?.nationality || '')
  const [saving, setSaving] = useState(false)
  const [sync, setSync] = useState(null) // null | {detail}
  const passportTouched = useRef(false)
  const destination = useRef('/')
  const cardRef = useRef(null)
  const firstView = useRef(true)

  const active = loaded && enabled && !!token

  // Resume from the server's step (a done onboarding opened again starts over).
  useEffect(() => {
    if (!active) return undefined
    let alive = true
    getAccount(token)
      .then((acc) => {
        if (!alive) return
        const ob = acc?.onboarding
        const saved = Number.isInteger(ob?.step) && !ob?.done ? Math.min(Math.max(ob.step, 1), STEPS) : 1
        setResumed(saved > 1)
        setStep(saved === 4 && !canNotify ? 5 : saved)
      })
      .catch(() => { if (alive) setStep(1) })
    return () => { alive = false }
  }, [active, token, canNotify])

  // Report each step as it is shown; move focus to it for screen readers.
  useEffect(() => {
    if (step === null) return
    quietly(() => putOnboarding(token, { step, done: false }))
    emit('onboarding_step', { step, action: 'view' })
    if (firstView.current) { firstView.current = false; return }
    try { cardRef.current?.focus({ preventScroll: true }) } catch { /* ignored */ }
  }, [step])

  // Preferences can arrive after the page: pre-fill the passport once.
  useEffect(() => {
    if (!passportTouched.current && preferences?.nationality) setPassport(preferences.nationality)
  }, [preferences?.nationality])

  const updateAnswers = useCallback((next) => {
    setAnswers(next)
    saveQuizAnswers(userId, next)
  }, [userId])

  const go = (target, action) => {
    if (action) emit('onboarding_step', { step, action })
    let next = target
    if (next === 4 && !canNotify) next = step < 4 ? 5 : 3
    if (next === 2) setQuestion(step > 2 ? RESULT : 0)
    setStep(next)
  }

  // ── quiz ──────────────────────────────────────────────────────────────────
  const reportResult = (forAnswers) => {
    const { primary, secondary } = classify(forAnswers)
    emit('onboarding_result', { type: primary.toLowerCase(), secondary: secondary.length })
  }
  const advance = (forAnswers) => {
    if (question + 1 >= RESULT) { setQuestion(RESULT); reportResult(forAnswers) } else setQuestion(question + 1)
  }
  const toggle = (optionId) => {
    const q = QUESTIONS[question]
    const current = Array.isArray(answers[q.id]) ? answers[q.id] : []
    const picked = q.multiChoice
      ? (current.includes(optionId) ? current.filter((id) => id !== optionId) : [...current, optionId])
      : [optionId]
    updateAnswers({ ...answers, [q.id]: picked })
  }
  const skipQuestion = () => {
    const next = { ...answers }
    delete next[QUESTIONS[question].id]
    updateAnswers(next)
    advance(next)
  }

  // ── finish / skip ─────────────────────────────────────────────────────────
  const leave = (to) => {
    markOnboardingSeen()
    navigate(to, { replace: true })
  }

  const complete = async () => {
    emit('onboarding_step', { step: 5, action: 'done' })
    try {
      const res = await putOnboarding(token, {
        step: 5, done: true, traveller_type: classify(answers).primary.toLowerCase(),
      })
      announceGame(res?.game)
    } catch { /* the account keeps its step; nothing else depends on it */ }
    leave(destination.current)
  }

  const syncAndFinish = async () => {
    setSaving(true)
    setSync(null)
    try {
      const current = await preferencesRequest(token)
      const merged = mergeQuizAnswers(current, answers)
      const nationality = passport.trim()
      if (nationality) merged.nationality = nationality
      delete merged.username
      delete merged.updated_at
      await preferencesRequest(token, merged)
      quietly(() => refreshPreferences?.())
    } catch (err) {
      setSaving(false)
      setSync({ detail: err?.message || '' })
      return
    }
    await complete()
  }

  const finish = (to) => {
    destination.current = to
    syncAndFinish()
  }

  const continueUnsynced = async () => {
    setSaving(true)
    await complete()
  }

  const skipAll = () => {
    emit('onboarding_step', { step, action: 'skip' })
    quietly(() => putOnboarding(token, { step, done: true, skipped: true }))
    leave('/')
  }

  if (!active) return null

  return (
    <main
      data-tid="onboarding.page"
      className="min-h-screen bg-gradient-to-br from-teal-50 via-slate-50 to-sky-50 px-4 py-6 sm:py-12"
    >
      <div className="mx-auto w-full max-w-xl">
        <header className="flex items-center justify-between gap-3 mb-4">
          <span className="font-display text-lg font-semibold text-teal-800">Voyager</span>
          {step !== null && (
            <button type="button" data-tid="onboarding.skip-all" onClick={skipAll} disabled={saving} className={secondaryBtn}>
              {t('web.skipAll')}
            </button>
          )}
        </header>

        <div
          ref={cardRef}
          tabIndex={-1}
          className="bg-white rounded-3xl shadow-xl ring-1 ring-gray-100 p-5 sm:p-8 space-y-6 outline-none"
        >
          {step === null ? (
            <div data-tid="onboarding.loading" aria-busy="true" className="h-48 rounded-2xl bg-gray-100 motion-safe:animate-pulse" />
          ) : (
            <>
              <OnboardingProgress current={step} count={STEPS} label={t('nav.stepOf', { step, count: STEPS })} />
              {resumed && (
                <p data-tid="onboarding.resume" role="status" className="text-sm text-teal-900 bg-teal-50 rounded-xl px-4 py-2.5">
                  {t('web.resume')}
                </p>
              )}

              {step === 1 && (
                <section data-tid="onboarding.step.welcome" aria-labelledby="onboarding-welcome-title" className="space-y-5">
                  <div>
                    <h1 id="onboarding-welcome-title" className="font-display text-2xl sm:text-3xl font-semibold text-gray-900">
                      {t('steps.welcome.title')}
                    </h1>
                    <p className="text-sm sm:text-base text-gray-700 mt-2">{t('steps.welcome.body')}</p>
                  </div>
                  <p className="text-sm text-gray-600">{t('steps.howYouTravel.body')}</p>
                  <div className="flex justify-end">
                    <button type="button" data-tid="onboarding.next" onClick={() => go(2, 'next')} className={primaryBtn}>
                      {t('web.getStarted')}
                    </button>
                  </div>
                </section>
              )}

              {step === 2 && (
                <div className="space-y-4">
                  <p className="text-xs font-semibold uppercase tracking-wide text-teal-800">{t('steps.howYouTravel.title')}</p>
                  {question < RESULT ? (
                    <QuizStep
                      key={question}
                      index={question}
                      selected={Array.isArray(answers[QUESTIONS[question].id]) ? answers[QUESTIONS[question].id] : []}
                      onToggle={toggle}
                      onBack={() => (question === 0 ? go(1) : setQuestion(question - 1))}
                      onSkip={skipQuestion}
                      onNext={() => advance(answers)}
                    />
                  ) : (
                    <TravellerTypeResult
                      answers={answers}
                      onChangeAnswers={() => setQuestion(0)}
                      onContinue={() => go(3, 'next')}
                    />
                  )}
                </div>
              )}

              {step === 3 && (
                <HomePassportStep
                  airport={airport}
                  passport={passport}
                  onAirport={setAirport}
                  onPassport={(v) => { passportTouched.current = true; setPassport(v) }}
                  onBack={() => go(2)}
                  onSkip={() => go(4, 'skip')}
                  onNext={() => { saveHomeAirport(userId, airport.trim()); go(4, 'next') }}
                />
              )}

              {step === 4 && (
                <NotificationsStep onBack={() => go(3)} onDone={(action) => go(5, action)} />
              )}

              {step === 5 && (
                <FirstTripStep
                  saving={saving}
                  syncError={sync}
                  onBack={() => go(4)}
                  onFinish={finish}
                  onRetry={syncAndFinish}
                  onContinueUnsynced={continueUnsynced}
                />
              )}
            </>
          )}
        </div>
      </div>
    </main>
  )
}
