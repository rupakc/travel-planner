const GRADE_COLOR = {
  A: '#14b8a6', // teal-500
  B: '#22c55e', // green-500
  C: '#f59e0b', // amber-500
  D: '#f97316', // orange-500
  F: '#ef4444', // red-500
}

const STATUS_DOT = {
  good:    'bg-teal-500',
  ok:      'bg-amber-500',
  warning: 'bg-orange-500',
  bad:     'bg-red-500',
}

export default function TripHealthCard({ score = 0, grade = 'C', factors = [], warnings = [] }) {
  const gradeColor = GRADE_COLOR[grade] ?? GRADE_COLOR['C']
  const deg = Math.max(0, Math.min(360, score * 3.6))

  return (
    <div className="bg-white rounded-xl border border-gray-200 p-4 space-y-3">
      {/* Top row: score ring + grade */}
      <div className="flex items-center gap-4">
        {/* Donut ring */}
        <div
          className="relative flex-shrink-0"
          style={{ width: 72, height: 72 }}
        >
          <div
            style={{
              width: 72,
              height: 72,
              borderRadius: '50%',
              background: `conic-gradient(${gradeColor} ${deg}deg, #e2e8f0 0)`,
            }}
          />
          {/* Inner white circle */}
          <div
            style={{
              position: 'absolute',
              top: '50%',
              left: '50%',
              transform: 'translate(-50%, -50%)',
              width: 50,
              height: 50,
              borderRadius: '50%',
              background: '#fff',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
            }}
          >
            <span className="text-lg font-bold text-gray-800">{score}</span>
          </div>
        </div>

        {/* Grade + label */}
        <div>
          <div
            className="text-4xl font-extrabold leading-none"
            style={{ color: gradeColor }}
          >
            {grade}
          </div>
          <div className="text-xs text-gray-500 mt-0.5">Trip Health</div>
        </div>
      </div>

      {/* Factor list */}
      {factors.length > 0 && (
        <ul className="space-y-2">
          {factors.map((f, i) => {
            const ratio = f.max > 0 ? Math.min(1, (f.score ?? 0) / f.max) : 0
            const dotClass = STATUS_DOT[f.status] ?? STATUS_DOT['ok']
            return (
              <li key={i} className="space-y-0.5">
                <div className="flex items-center justify-between gap-2">
                  <div className="flex items-center gap-1.5 min-w-0">
                    <span className={`w-2 h-2 rounded-full flex-shrink-0 ${dotClass}`} />
                    <span className="text-xs font-medium text-gray-700 truncate">{f.name}</span>
                  </div>
                  <span className="text-xs text-gray-400 flex-shrink-0">
                    {f.score}/{f.max}
                  </span>
                </div>
                {/* Mini progress bar */}
                <div className="h-1 rounded-full bg-gray-100 overflow-hidden">
                  <div
                    className="h-full rounded-full transition-all"
                    style={{
                      width: `${ratio * 100}%`,
                      backgroundColor: gradeColor,
                    }}
                  />
                </div>
                {f.message && (
                  <p className="text-xs text-gray-500 pl-3.5">{f.message}</p>
                )}
              </li>
            )
          })}
        </ul>
      )}

      {/* Warning chips */}
      {warnings.length > 0 && (
        <div className="flex flex-wrap gap-1.5 pt-1">
          {warnings.map((w, i) => (
            <span
              key={i}
              className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-red-500 text-white"
            >
              {w.message}
            </span>
          ))}
        </div>
      )}
    </div>
  )
}
