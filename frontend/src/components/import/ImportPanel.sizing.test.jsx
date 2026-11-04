// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { act } from 'react'
import { createRoot } from 'react-dom/client'

vi.mock('../../services/api', () => ({ extractImport: vi.fn() }))
vi.mock('../../utils/analytics', () => ({ track: vi.fn() }))
vi.mock('../../utils/linkImport', async (importOriginal) => ({
  ...(await importOriginal()),
  prepareScreenshot: vi.fn(),
}))

import { prepareScreenshot } from '../../utils/linkImport'
import ImportPanel from './ImportPanel'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

describe('screenshots are shrunk before the size check', () => {
  let container, root
  beforeEach(() => {
    container = document.createElement('div')
    document.body.appendChild(container)
    root = createRoot(container)
    act(() => root.render(<ImportPanel token="tok" onPreview={() => {}} />))
  })
  afterEach(() => {
    act(() => root.unmount())
    container.remove()
  })
  const drop = async (file) => {
    const input = container.querySelector('input[type="file"]')
    await act(async () => {
      Object.defineProperty(input, 'files', { value: [file], configurable: true })
      input.dispatchEvent(new Event('change', { bubbles: true }))
      await new Promise((r) => setTimeout(r, 5))
    })
  }
  const bigPng = () => {
    const file = new File(['x'], 'retina.png', { type: 'image/png' })
    Object.defineProperty(file, 'size', { value: 8 * 1024 * 1024 })
    return file
  }

  it('accepts an 8 MB retina PNG that shrinks to a small upload', async () => {
    prepareScreenshot.mockResolvedValue({ media_type: 'image/webp', data_base64: 'A'.repeat(400_000) })
    await drop(bigPng())
    expect(container.querySelectorAll('[data-shot]')).toHaveLength(1)
    expect(container.textContent).not.toMatch(/over 5 MB/)
  })

  it('still refuses one that stays too big after shrinking', async () => {
    prepareScreenshot.mockResolvedValue({ media_type: 'image/png', data_base64: 'A'.repeat(5 * 1024 * 1024 + 10) })
    await drop(bigPng())
    expect(container.querySelectorAll('[data-shot]')).toHaveLength(0)
    expect(container.textContent).toMatch(/too big/i)
  })
})
