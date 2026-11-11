// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { startAutocapture } from './autocapture'
import { routeTemplate } from './routes'

describe('routeTemplate', () => {
  it('keeps tokens and ids out of routes', () => {
    expect(routeTemplate('/share/abc123')).toBe('/share/:token')
    expect(routeTemplate('/share/abc123/')).toBe('/share/:token')
    expect(routeTemplate('/plans/42')).toBe('/plans/:id')
    expect(routeTemplate('/verify')).toBe('/verify')
    expect(routeTemplate('/account')).toBe('/account')
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
    expect(emit).toHaveBeenCalledWith('ui_change', { tid: 'login.user', route: '/' })
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

  it('selects and textareas emit ui_change without a value', () => {
    document.body.innerHTML = '<select data-tid="search.pace"><option value="slow">Slow</option></select><textarea data-tid="feedback.text"></textarea>'
    document.querySelector('select').dispatchEvent(new Event('change', { bubbles: true }))
    const ta = document.querySelector('textarea')
    ta.value = 'my secret note'
    ta.dispatchEvent(new Event('change', { bubbles: true }))
    expect(emit.mock.calls).toEqual([
      ['ui_change', { tid: 'search.pace', route: '/' }],
      ['ui_change', { tid: 'feedback.text', route: '/' }],
    ])
  })

  it('radios and role=switch emit ui_toggle with on', () => {
    document.body.innerHTML = '<input type="radio" data-tid="pace.slow"><button role="switch" aria-checked="false" data-tid="prefs.dark">D</button>'
    const radio = document.querySelector('input')
    radio.checked = true
    radio.dispatchEvent(new Event('change', { bubbles: true }))
    expect(emit).toHaveBeenLastCalledWith('ui_toggle', { tid: 'pace.slow', route: '/', on: true })
    click(document.querySelector('button'))
    expect(emit).toHaveBeenLastCalledWith('ui_toggle', { tid: 'prefs.dark', route: '/', on: true })
  })

  it('never sends entity ids from element ids (digits or uuid-like segments)', () => {
    document.body.innerHTML = [
      '<div id="watch-123"><button>a</button></div>',
      '<div id="nearby-5f3a9c1e"><button>b</button></div>',
      '<div id="section-deadbeefcafe"><button>c</button></div>',
      '<div id="results-panel"><button>d</button></div>',
    ].join('')
    for (const b of document.querySelectorAll('button')) click(b)
    expect(emit.mock.calls.map(([, p]) => p.tid)).toEqual(['auto:button', 'auto:button', 'auto:button', 'id:results-panel'])
    expect(JSON.stringify(emit.mock.calls)).not.toMatch(/123|5f3a9c1e|deadbeef/)
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
