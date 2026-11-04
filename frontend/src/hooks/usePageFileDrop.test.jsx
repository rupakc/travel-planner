// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import usePageFileDrop from './usePageFileDrop'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

function Page({ onFiles }) {
  const { dragging, handlers } = usePageFileDrop(onFiles)
  return (
    <div data-page {...handlers}>
      {dragging && <div data-overlay />}
      <div data-zone onDrop={(e) => e.preventDefault()} />
    </div>
  )
}

function fire(el, type, { files = [], related = null } = {}) {
  const evt = new Event(type, { bubbles: true, cancelable: true })
  Object.defineProperty(evt, 'dataTransfer', { value: { types: ['Files'], files } })
  Object.defineProperty(evt, 'relatedTarget', { value: related })
  act(() => { el.dispatchEvent(evt) })
}

describe('usePageFileDrop', () => {
  let container, root, onFiles
  const overlay = () => container.querySelector('[data-overlay]')
  beforeEach(() => {
    container = document.createElement('div')
    document.body.appendChild(container)
    root = createRoot(container)
    onFiles = vi.fn()
    act(() => root.render(<Page onFiles={onFiles} />))
  })
  afterEach(() => {
    act(() => root.unmount())
    container.remove()
  })

  it('shows the overlay on drag and hands page drops over', () => {
    const page = container.querySelector('[data-page]')
    fire(page, 'dragenter')
    expect(overlay()).not.toBeNull()
    const file = new File(['x'], 'shot.png', { type: 'image/png' })
    fire(page, 'drop', { files: [file] })
    expect(overlay()).toBeNull()
    expect(onFiles).toHaveBeenCalledWith([file])
  })

  it('clears the overlay when a drop zone inside handles the drop (the stuck-overlay bug)', () => {
    const zone = container.querySelector('[data-zone]')
    fire(zone, 'dragenter')
    fire(zone, 'dragenter')
    expect(overlay()).not.toBeNull()
    fire(zone, 'drop', { files: [new File(['x'], 'a.png', { type: 'image/png' })] })
    expect(overlay()).toBeNull()
    expect(onFiles).not.toHaveBeenCalled() // the zone already took the file
  })

  it('clears on dragend and when the drag leaves the window', () => {
    const page = container.querySelector('[data-page]')
    fire(page, 'dragenter')
    act(() => { window.dispatchEvent(new Event('dragend')) })
    expect(overlay()).toBeNull()
    fire(page, 'dragenter')
    fire(page, 'dragenter')
    fire(document.body, 'dragleave', { related: null })
    expect(overlay()).toBeNull()
  })
})
