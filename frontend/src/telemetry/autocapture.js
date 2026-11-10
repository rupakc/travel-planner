// Delegated auto-capture of taps, toggles and submits. Elements are named by
// their closest data-tid (else id:<id>, else auto:<tag>); input values and
// text content are never read.

import { currentRoute } from './routes'

const ID_RE = /^[A-Za-z0-9_.:/-]{1,64}$/
const INTERACTIVE = [
  '[data-tid]', 'a', 'button', 'input', 'select', 'textarea', 'summary', 'label',
  '[role="button"]', '[role="tab"]', '[role="menuitem"]', '[role="link"]',
  '[role="switch"]', '[role="checkbox"]', '[role="option"]',
].join(',')

function elementId(el) {
  const tagged = el.closest('[data-tid]')
  const tid = tagged?.getAttribute('data-tid')
  if (tid && ID_RE.test(tid)) return tid
  const withId = el.closest('[id]')
  const id = withId?.id
  // React's useId values (":r1:") say nothing about the element.
  if (id && !id.startsWith(':')) {
    const value = `id:${id}`
    if (ID_RE.test(value)) return value
  }
  return `auto:${el.tagName.toLowerCase()}`
}

const targetElement = (event) => {
  const t = event.target
  return t && t.nodeType === 1 ? t : t?.parentElement || null
}

export function startAutocapture(emit) {
  const onClick = (event) => {
    try {
      const el = targetElement(event)?.closest(INTERACTIVE)
      if (!el) return
      emit('ui_tap', { tid: elementId(el), route: currentRoute() })
    } catch { /* never break the page */ }
  }

  const onChange = (event) => {
    try {
      const el = targetElement(event)
      if (!el) return
      const props = { tid: elementId(el), route: currentRoute() }
      const type = el.tagName === 'INPUT' ? el.type : ''
      if (type === 'checkbox' || type === 'radio') props.on = !!el.checked
      emit('ui_toggle', props)
    } catch { /* never break the page */ }
  }

  const onSubmit = (event) => {
    try {
      const el = targetElement(event)
      if (!el) return
      emit('ui_submit', { tid: elementId(el), route: currentRoute() })
    } catch { /* never break the page */ }
  }

  const opts = { capture: true, passive: true }
  document.addEventListener('click', onClick, opts)
  document.addEventListener('change', onChange, opts)
  document.addEventListener('submit', onSubmit, opts)
  return () => {
    document.removeEventListener('click', onClick, opts)
    document.removeEventListener('change', onChange, opts)
    document.removeEventListener('submit', onSubmit, opts)
  }
}
