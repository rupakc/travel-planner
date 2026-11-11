// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach } from 'vitest'
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import Avatar from './Avatar'

globalThis.IS_REACT_ACT_ENVIRONMENT = true
let container, root
beforeEach(() => { container = document.createElement('div'); document.body.appendChild(container); root = createRoot(container) })
afterEach(() => { act(() => root.unmount()); container.remove() })

describe('Avatar', () => {
  it('shows initials without a picture', () => {
    act(() => root.render(<Avatar user={{ username: 'jane_doe', display_name: 'Jane Doe', avatar_url: null }} />))
    expect(container.textContent).toBe('JD')
    expect(container.querySelector('img')).toBeNull()
  })
  it('falls back to initials when the image fails to load', () => {
    act(() => root.render(<Avatar user={{ username: 'jane', display_name: 'Jane', avatar_url: '/api/avatars/x.webp' }} />))
    const img = container.querySelector('img')
    expect(img).not.toBeNull()
    act(() => { img.dispatchEvent(new Event('error')) })
    expect(container.querySelector('img')).toBeNull()
    expect(container.textContent).toBe('J')
  })
})
