// @vitest-environment node
// public/sw.js runs in a node:vm context with a fake `self`, `caches` and
// `fetch`: the real worker script, no browser.
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'

const SOURCE = readFileSync(new URL('../../public/sw.js', import.meta.url), 'utf8')
const ORIGIN = 'https://voyager.test'

class FakeCache {
  constructor() { this.entries = new Map() }
  keyOf(req) { return new URL(typeof req === 'string' ? req : req.url, ORIGIN).pathname }
  async match(req) { const hit = this.entries.get(this.keyOf(req)); return hit ? hit.clone() : undefined }
  async put(req, res) { this.entries.set(this.keyOf(req), res) }
  async delete(req) { return this.entries.delete(this.keyOf(req)) }
  async keys() { return [...this.entries.keys()].map((p) => ({ url: ORIGIN + p })) }
}

class FakeCaches {
  constructor() { this.stores = new Map() }
  async open(name) { if (!this.stores.has(name)) this.stores.set(name, new FakeCache()); return this.stores.get(name) }
  async keys() { return [...this.stores.keys()] }
  async delete(name) { return this.stores.delete(name) }
  async has(name) { return this.stores.has(name) }
}

let handlers, caches, fetchMock

function load() {
  handlers = {}
  caches = new FakeCaches()
  fetchMock = vi.fn()
  const self = {
    location: new URL(`${ORIGIN}/sw.js`),
    addEventListener: (type, fn) => { handlers[type] = fn },
    skipWaiting: vi.fn(async () => {}),
    clients: { claim: vi.fn(async () => {}) },
  }
  const context = vm.createContext({
    self, caches, fetch: (...args) => fetchMock(...args), Response, Request, URL, Promise, console,
  })
  vm.runInContext(SOURCE, context, { filename: 'sw.js' })
}

// Dispatches a fetch event; resolves with the response passed to
// respondWith, or `null` when the worker let the request through.
async function dispatchFetch(url, { mode = 'cors', method = 'GET' } = {}) {
  let responded = null
  const event = {
    request: { url: `${ORIGIN}${url}`, mode, method },
    respondWith: (p) => { responded = Promise.resolve(p) },
    waitUntil: () => {},
  }
  handlers.fetch(event)
  return responded ? await responded : null
}

async function message(data) {
  const waits = []
  const reply = vi.fn()
  handlers.message({ data, ports: [{ postMessage: reply }], waitUntil: (p) => waits.push(p) })
  await Promise.all(waits)
  return reply
}

beforeEach(load)

describe('sw.js', () => {
  it('navigation falls back to the cached shell', async () => {
    const shell = await caches.open('voyager-shell-1.0.0')
    await shell.put('/index.html', new Response('<html>shell</html>'))
    fetchMock.mockRejectedValue(new TypeError('Failed to fetch'))
    const res = await dispatchFetch('/trips/12/offline', { mode: 'navigate' })
    expect(await res.text()).toBe('<html>shell</html>')
  })

  it('navigation goes to the network first when online', async () => {
    const shell = await caches.open('voyager-shell-1.0.0')
    await shell.put('/index.html', new Response('old'))
    fetchMock.mockResolvedValue(new Response('fresh'))
    const res = await dispatchFetch('/trips', { mode: 'navigate' })
    expect(await res.text()).toBe('fresh')
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('does not intercept /api/trips (nor other non-asset requests or writes)', async () => {
    expect(await dispatchFetch('/api/trips')).toBeNull()
    expect(await dispatchFetch('/api/trips/12/offline-pack')).toBeNull()
    expect(await dispatchFetch('/api/trips', { mode: 'navigate' })).toBeNull()
    expect(await dispatchFetch('/health')).toBeNull()
    expect(await dispatchFetch('/sw-assets.json')).toBeNull()
    expect(await dispatchFetch('/assets/a.js', { method: 'POST' })).toBeNull()
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('serves /assets/a.js from the cache, else the network', async () => {
    const shell = await caches.open('voyager-shell-1.0.0')
    await shell.put('/assets/a.js', new Response('cached js'))
    const hit = await dispatchFetch('/assets/a.js')
    expect(await hit.text()).toBe('cached js')
    expect(fetchMock).not.toHaveBeenCalled()

    fetchMock.mockResolvedValue(new Response('net js'))
    const miss = await dispatchFetch('/assets/b.js')
    expect(await miss.text()).toBe('net js')
  })

  it('precache fills the new version cache, deletes the old version caches and replies {ok, bytes}', async () => {
    await caches.open('voyager-shell-0.9.0')
    await caches.open('someone-else')
    const manifest = {
      version: '1.0.0',
      shell: ['/', '/index.html', '/theme-init.js', '/favicon.svg', '/manifest.webmanifest'],
      assets: ['/assets/a.js', '/assets/b.css'],
    }
    fetchMock.mockImplementation(async (url, init) => {
      if (url === '/sw-assets.json') {
        expect(init?.cache).toBe('no-store')
        return new Response(JSON.stringify(manifest))
      }
      // manifest.webmanifest may not exist yet: optional shell files are skipped
      if (url === '/manifest.webmanifest') return new Response('nope', { status: 404 })
      return new Response(`body of ${url}`)
    })
    const reply = await message({ type: 'precache' })
    expect(reply).toHaveBeenCalledTimes(1)
    const answer = reply.mock.calls[0][0]
    expect(answer.ok).toBe(true)
    expect(answer.bytes).toBeGreaterThan(0)
    expect((await caches.keys()).sort()).toEqual(['someone-else', 'voyager-shell-1.0.0'])
    const cache = await caches.open('voyager-shell-1.0.0')
    expect(await (await cache.match('/assets/a.js')).text()).toBe('body of /assets/a.js')
    expect(await cache.match('/manifest.webmanifest')).toBeUndefined()
  })

  it('a failed asset keeps the previous version and answers ok: false', async () => {
    const old = await caches.open('voyager-shell-0.9.0')
    await old.put('/index.html', new Response('old shell'))
    fetchMock.mockImplementation(async (url) => {
      if (url === '/sw-assets.json') return new Response(JSON.stringify({ version: '1.0.0', shell: ['/index.html'], assets: ['/assets/a.js'] }))
      if (url === '/assets/a.js') throw new TypeError('Failed to fetch')
      return new Response('x')
    })
    const reply = await message({ type: 'precache' })
    expect(reply.mock.calls[0][0].ok).toBe(false)
    expect(await caches.keys()).toEqual(['voyager-shell-0.9.0'])
  })

  it('purge deletes every voyager-* cache', async () => {
    await caches.open('voyager-shell-1.0.0')
    await caches.open('voyager-other')
    await caches.open('someone-else')
    const reply = await message({ type: 'purge' })
    expect(reply.mock.calls[0][0]).toEqual({ ok: true })
    expect(await caches.keys()).toEqual(['someone-else'])
  })
})
