import { lazy, Suspense } from 'react'

const ScratchMapSvg = lazy(() => import('./ScratchMapSvg'))

// Drawn world map with visited countries filled. The list below it stays the
// accessible fallback; the map is hidden from nothing when the chunk fails.
export default function ScratchMap({ countries }) {
  return (
    <div className="mb-4">
      <Suspense fallback={null}>
        <ScratchMapSvg countries={countries} />
      </Suspense>
    </div>
  )
}
