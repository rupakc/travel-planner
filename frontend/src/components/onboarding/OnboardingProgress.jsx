// A segmented progress bar with its "Step n of m" (or "Question n of m") label.
export default function OnboardingProgress({ current, count, label, tid = 'onboarding.progress' }) {
  return (
    <div data-tid={tid}>
      <p className="text-xs font-medium text-gray-600 mb-1.5">{label}</p>
      <div
        role="progressbar"
        aria-valuemin={1}
        aria-valuemax={count}
        aria-valuenow={current}
        aria-label={label}
        className="flex gap-1"
      >
        {Array.from({ length: count }, (_, i) => (
          <span
            key={i}
            className={`h-1.5 flex-1 rounded-full ${i < current ? 'bg-teal-700' : 'bg-gray-200'}`}
          />
        ))}
      </div>
    </div>
  )
}
