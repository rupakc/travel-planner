import { useEffect, useRef, useState, useCallback } from 'react'

const hasFiles = (e) => [...(e.dataTransfer?.types || [])].includes('Files')

/**
 * A full-page "drop a file here" overlay. `dragging` is true while files are
 * dragged over the element the `handlers` are spread on. A drop that an inner
 * drop zone already handled (it called preventDefault) only clears the
 * overlay; other drops call onFiles(files). Browsers fire no dragleave after
 * a drop, so drop, dragend and leaving the window all reset it too.
 */
export default function usePageFileDrop(onFiles) {
  const [dragging, setDragging] = useState(false)
  const depth = useRef(0)
  const reset = useCallback(() => {
    depth.current = 0
    setDragging(false)
  }, [])

  useEffect(() => {
    const onLeaveWindow = (e) => { if (!e.relatedTarget) reset() }
    window.addEventListener('drop', reset, true)
    window.addEventListener('dragend', reset, true)
    window.addEventListener('dragleave', onLeaveWindow, true)
    return () => {
      window.removeEventListener('drop', reset, true)
      window.removeEventListener('dragend', reset, true)
      window.removeEventListener('dragleave', onLeaveWindow, true)
    }
  }, [reset])

  const handlers = {
    onDragEnter: (e) => {
      if (!hasFiles(e)) return
      depth.current += 1
      setDragging(true)
    },
    onDragOver: (e) => { if (hasFiles(e)) e.preventDefault() },
    onDragLeave: (e) => {
      if (!hasFiles(e)) return
      depth.current = Math.max(0, depth.current - 1)
      if (!depth.current) setDragging(false)
    },
    onDrop: (e) => {
      reset()
      if (!hasFiles(e) || e.defaultPrevented) return
      e.preventDefault()
      onFiles([...(e.dataTransfer.files || [])])
    },
  }
  return { dragging, handlers }
}
