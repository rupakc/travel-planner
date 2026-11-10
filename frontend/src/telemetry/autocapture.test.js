// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { startAutocapture } from './autocapture'
import { routeTemplate } from './routes'

describe('routeTemplate', () => {
  it('keeps tokens and ids out of routes', () => {
    expect(routeTemplate('/share/abc123')).toBe('/share/:token')
    expect(routeTemplate('/share/abc123/')).toBe('/share/:token')
    expect(routeTemplate('/plans/42')).toBe('/plans/:id')
  })

  it('passes known static routes through', () => {
    for (const p of ['/', '/chat', '/nearby', '/preferences', '/alerts', '/admin', '/login', '/change-password']) {
      expect(routeTemplate(p)).toBe(p)
    }
    expect(routeTemplate('/chat/')).toBe('/chat')
    expect(routeTemplate('')).toBe('/')
  })

  it('collapses unknown paths so nothing user-specific leaks', () => {
    expect(routeTemplate('/jane@x.com')).toBe('/other')
    expect(routeTemplate('/some/deep/path')).toBe('/other')
    expect(routeTemplate(undefined)).toBe('/')
  })
})

describe('autocapture', () => {
  let emit, stop
  beforeEach(() => {
    emit = vi.fn()
    window.history.pushState({}, '', '/')
    stop = startAutocapture(emit)
  })
  afterEach(() => {
    stop()
    document.body.innerHTML = ''
  })

  const click = (el) => el.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }))

  it('emits ui_tap with the closest data-tid and the route template', () => {
    document.body.innerHTML = '<main><button data-tid="search.submit"><span>Go</span></button></main>'
    click(document.querySelector('span'))
    expect(emit).toHaveBeenCalledWith('ui_tap', { tid: 'search.submit', route: '/' })
  })

  it('uses the route template, never the raw path', () => {
    window.history.pushState({}, '', '/share/secret-token-1')
    document.body.innerHTML = '<button data-tid="share.copy">Copy</button>'
    click(document.querySelector('button'))
    expect(emit).toHaveBeenCalledWith('ui_tap', { tid: 'share.copy', route: '/share/:token' })
  })

  it('falls back to id:<id>, then auto:<tag>', () => {
    document.body.innerHTML = '<div id="panel"><button>A</button></div><a href="#x">B</a>'
    click(document.querySelector('button'))
    expect(emit).toHaveBeenLastCalledWith('ui_tap', { tid: 'id:panel', route: '/' })
    click(document.querySelector('a'))
    expect(emit).toHaveBeenLastCalledWith('ui_tap', { tid: 'auto:a', route: '/' })
  })

  it('ignores clicks on non-interactive elements', () => {
    document.body.innerHTML = '<p>Just text</p>'
    click(document.querySelector('p'))
    expect(emit).not.toHaveBeenCalled()
  })

  it('never sends input values or text content', () => {
    document.body.innerHTML = '<form data-tid="login.form"><input data-tid="login.user" value=""><button>Sign in jane</button></form>'
    const input = document.querySelector('input')
    input.value = 'jane@x.com'
    input.dispatchEvent(new Event('change', { bubbles: true }))
    expect(emit).toHaveBeenCalledWith('ui_toggle', { tid: 'login.user', route: '/' })
    document.querySelector('form').dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }))
    expect(emit).toHaveBeenCalledWith('ui_submit', { tid: 'login.form', route: '/' })
    const sent = JSON.stringify(emit.mock.calls)
    expect(sent).not.toContain('jane')
    expect(sent).not.toContain('Sign in')
  })

  it('reports checkbox state as a boolean', () => {
    document.body.innerHTML = '<input type="checkbox" data-tid="prefs.email">'
    const box = document.querySelector('input')
    box.checked = true
    box.dispatchEvent(new Event('change', { bubbles: true }))
    expect(emit).toHaveBeenCalledWith('ui_toggle', { tid: 'prefs.email', route: '/', on: true })
  })

  it('drops tids that would fail the server id rule', () => {
    document.body.innerHTML = '<button data-tid="has space">x</button><button id="has space">y</button>'
    click(document.querySelectorAll('button')[0])
    expect(emit).toHaveBeenLastCalledWith('ui_tap', { tid: 'auto:button', route: '/' })
    click(document.querySelectorAll('button')[1])
    expect(emit).toHaveBeenLastCalledWith('ui_tap', { tid: 'auto:button', route: '/' })
  })

  it('stops listening after stop()', () => {
    stop()
    document.body.innerHTML = '<button data-tid="x">x</button>'
    click(document.querySelector('button'))
    expect(emit).not.toHaveBeenCalled()
  })

  it('never throws even when emit throws', () => {
    emit.mockImplementation(() => { throw new Error('boom') })
    document.body.innerHTML = '<button data-tid="x">x</button>'
    expect(() => click(document.querySelector('button'))).not.toThrow()
  })
})
