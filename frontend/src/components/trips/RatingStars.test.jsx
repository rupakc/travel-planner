// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import RatingStars from './RatingStars'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

describe('RatingStars', () => {
  let container, root
  const mount = (props) => act(() => root.render(<RatingStars {...props} />))
  const radio = (label) => container.querySelector(`[role="radio"][aria-label="${label}"]`)
  const key = (el, k) => act(() => { el.dispatchEvent(new KeyboardEvent('keydown', { key: k, bubbles: true })) })

  beforeEach(() => { container = document.createElement('div'); document.body.appendChild(container); root = createRoot(container) })
  afterEach(() => { act(() => root.unmount()); container.remove() })

  it('is a radio group labelled "n of 5 stars"', () => {
    mount({ value: 3, onChange: () => {} })
    expect(container.querySelectorAll('[role="radio"]')).toHaveLength(5)
    expect(radio('3 of 5 stars').getAttribute('aria-checked')).toBe('true')
    expect(container.querySelector('[role="radiogroup"]')).not.toBeNull()
  })

  it('arrow keys change the rating', () => {
    const onChange = vi.fn()
    mount({ value: 3, onChange })
    key(radio('3 of 5 stars'), 'ArrowRight')
    expect(onChange).toHaveBeenLastCalledWith(4)
    key(radio('3 of 5 stars'), 'ArrowLeft')
    expect(onChange).toHaveBeenLastCalledWith(2)
  })

  it('clicking the chosen star clears the rating', () => {
    const onChange = vi.fn()
    mount({ value: 2, onChange })
    act(() => radio('2 of 5 stars').click())
    expect(onChange).toHaveBeenLastCalledWith(null)
  })
})
