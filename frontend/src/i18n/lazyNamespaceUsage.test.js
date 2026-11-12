// @vitest-environment node
// Guard for lazy namespaces: tests run with every namespace loaded
// (bundleAll), so a lazy namespace used outside I18nRouteGate would pass every
// test and show raw keys in production. This scans the import graph from
// main.jsx, stopping at the gated page modules (the only allow-list), and fails
// if any module still reachable references a lazy namespace.
import { describe, it, expect } from 'vitest'
import { readFileSync, existsSync, statSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join, relative, resolve } from 'node:path'
import { LAZY_NS } from './routeNamespaces'

const SRC = fileURLToPath(new URL('..', import.meta.url))

// Modules rendered only inside I18nRouteGate (App.jsx's on-demand routes).
// Anything they import may use lazy namespaces unless the shell imports it too.
const GATED_ENTRIES = [
  'pages/AccountPage.jsx', 'pages/AdminPage.jsx', 'pages/NearbyPage.jsx',
  'pages/TripsPage.jsx', 'pages/TripPage.jsx', 'pages/PlayPage.jsx', 'pages/YouPage.jsx',
].map((p) => join(SRC, p))

const IMPORT_RE = /(?:import|export)\s[^'"]*?from\s*['"]([^'"]+)['"]|import\(\s*['"]([^'"]+)['"]\s*\)|import\s+['"]([^'"]+)['"]/g

function resolveImport(from, spec) {
  if (!spec.startsWith('.')) return null
  const base = resolve(dirname(from), spec)
  for (const c of [base, `${base}.jsx`, `${base}.js`, join(base, 'index.js'), join(base, 'index.jsx')]) {
    if (existsSync(c) && statSync(c).isFile() && /\.jsx?$/.test(c)) return c
  }
  return null
}

const sources = new Map()
const read = (file) => {
  if (!sources.has(file)) sources.set(file, readFileSync(file, 'utf8'))
  return sources.get(file)
}

function closure(roots, stopAt) {
  const seen = new Set()
  const stack = [...roots]
  while (stack.length) {
    const file = stack.pop()
    if (seen.has(file) || stopAt.has(file)) continue
    seen.add(file)
    for (const m of read(file).matchAll(IMPORT_RE)) {
      const dep = resolveImport(file, m[1] || m[2] || m[3])
      if (dep) stack.push(dep)
    }
  }
  return seen
}

// Literal uses of `ns`: useTranslation('ns' | ['ns', …]), withTranslation(…),
// getFixedT(…, 'ns'), ns="ns" / ns: 'ns', and 'ns:key' / `ns:${…}` prefixes.
export function usesNamespace(src, ns) {
  const q = `['"\`]${ns}['"\`]`
  const patterns = [
    new RegExp(`(?:useTranslation|withTranslation|getFixedT)\\([^)]*${q}`),
    new RegExp(`\\bns\\s*[=:]\\s*\\{?\\s*(?:\\[[^\\]]*)?${q}`),
    new RegExp(`['"\`]${ns}:[A-Za-z_$]`),
  ]
  return patterns.some((re) => re.test(src))
}

const shell = closure([join(SRC, 'main.jsx')], new Set(GATED_ENTRIES))

describe('lazy namespaces stay inside I18nRouteGate', () => {
  it('finds uses (the scanner is not vacuous)', () => {
    expect(usesNamespace("const { t } = useTranslation('accountData')", 'accountData')).toBe(true)
    expect(usesNamespace("useTranslation(['common', 'trips'])", 'trips')).toBe(true)
    expect(usesNamespace("i18n.t(`security:${k}`)", 'security')).toBe(true)
    expect(usesNamespace('<Trans ns="today" i18nKey="x" />', 'today')).toBe(true)
    expect(usesNamespace("withTranslation('recap')(X)", 'recap')).toBe(true)
    expect(usesNamespace("useTranslation('trip')", 'trips')).toBe(false)
    const account = closure([join(SRC, 'pages/AccountPage.jsx')], new Set())
    expect([...account].some((f) => usesNamespace(read(f), 'accountData'))).toBe(true)
  })

  it('reaches the shell, the always-mounted pages and the ungated routes', () => {
    for (const p of ['App.jsx', 'pages/SearchPage.jsx', 'pages/ResultsPage.jsx', 'pages/ChatPage.jsx',
      'components/ui/NavBar.jsx', 'pages/LoginPage.jsx', 'pages/SharePage.jsx']) {
      expect(shell.has(join(SRC, p)), p).toBe(true)
    }
    for (const g of GATED_ENTRIES) expect(shell.has(g)).toBe(false)
  })

  it('no module outside the gated pages uses a lazy namespace', () => {
    const offenders = []
    for (const file of shell) {
      for (const ns of LAZY_NS) {
        if (usesNamespace(read(file), ns)) offenders.push(`${relative(SRC, file)} uses ${ns}`)
      }
    }
    expect(offenders).toEqual([])
  })
})
