// Offline UI smoke test: renders built routes in jsdom against a running API and prints visible text.
// Usage (from frontend/): TOKEN=<jwt> node smoke.mjs      (env: API, ROUTES, TOKEN)
import { JSDOM } from 'jsdom'
import fs from 'node:fs'
import path from 'node:path'

const dist = path.resolve('dist')
const html = fs.readFileSync(path.join(dist, 'index.html'), 'utf8')
const entryFile = html.match(/src="\/assets\/([^"]+\.js)"/)[1]
const prepare = (src) => src.replace(/import\.meta\.url/g, '"http://localhost:5173/"').replace(/import\.meta\.resolve/g, '(function(x){return x})')

// Vite emits real ES modules (code-split chunks). jsdom can't `import()` files, so we evaluate each
// chunk through a tiny module loader: static imports/exports are rewritten to a `__mods` registry and
// dynamic `import()`s become lookups – enough for the app bundle which only imports local chunks.
const cache = new Map()
function loadModule(window, file) {
  if (cache.has(file)) return cache.get(file)
  let src = prepare(fs.readFileSync(path.join(dist, 'assets', file), 'utf8'))
  const asProp = (names) => names.replace(/([\w$]+)\s+as\s+([\w$]+)/g, '$1: $2')
  src = src.replace(/import\s*\{([^}]*)\}\s*from\s*["']\.\/([^"']+)["'];?/g, (_, names, f) => `const {${asProp(names)}} = __req("${f}");`)
  src = src.replace(/import\s+([\w$]+)\s*from\s*["']\.\/([^"']+)["'];?/g, (_, name, f) => `const ${name} = __req("${f}").default;`)
  src = src.replace(/import\s*["']\.\/([^"']+)["'];?/g, (_, f) => `__req("${f}");`)
  src = src.replace(/import\(\s*["'`]\.\/([^"'`]+)["'`]\s*\)/g, (_, f) => `Promise.resolve(__req("${f}"))`)
  const exportsOut = []
  src = src.replace(/export\s*\{([^}]*)\};?/g, (_, names) => {
    names.split(',').map((n) => n.trim()).filter(Boolean).forEach((n) => { const [a, b] = n.split(/\s+as\s+/); exportsOut.push([b || a, a]) })
    return ''
  })
  src = src.replace(/export\s+default\s+/, 'const __default = ')
  if (/const __default = /.test(src)) exportsOut.push(['default', '__default'])
  const body = `${src}\nreturn {${exportsOut.map(([k, v]) => `${JSON.stringify(k)}: ${v}`).join(',')}};`
  const mod = {}
  cache.set(file, mod)
  const fn = window.eval(`(function(__req){${body}\n})`)
  Object.assign(mod, fn((f) => loadModule(window, f)))
  return mod
}
const API = process.env.API || 'http://localhost:8000'
const routes = (process.env.ROUTES || '/,/websites/1,/websites/1/google,/websites/1/keywords,/websites/1/settings').split(',')
const token = process.env.TOKEN || ''
// CLICKS='Label A|Label B' clicks buttons with that exact text (in order) after the first render, printing the text after each click.
const clicks = (process.env.CLICKS || '').split('|').filter(Boolean)

for (const route of routes) {
  const dom = new JSDOM(html.replace(/<script[^>]*src="[^"]*"[^>]*><\/script>/g, ''), {
    url: 'http://localhost:5173' + route, runScripts: 'outside-only', pretendToBeVisual: true,
    beforeParse(window) {
      window.localStorage.setItem('rankpilot_token', token)
      window.fetch = (u, o) => fetch(String(u).startsWith('/') ? API + u : u, o)
      const RealXHR = window.XMLHttpRequest
      window.XMLHttpRequest = class extends RealXHR { open(m, u, ...r) { return super.open(m, String(u).startsWith('/') ? API + u : u, ...r) } }
      window.ResizeObserver = class { observe() {} unobserve() {} disconnect() {} }
      window.scrollTo = () => {}
      window.URL.createObjectURL = () => 'blob:mock'; window.URL.revokeObjectURL = () => {}
      window.matchMedia = () => ({ matches: false, addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {} })
    },
  })
  const errors = []
  dom.window.addEventListener('error', (e) => errors.push(e.message))
  dom.virtualConsole.on('jsdomError', (e) => errors.push(String(e.message || e).slice(0, 200)))
  cache.clear()
  try { loadModule(dom.window, entryFile) } catch (e) { errors.push('eval: ' + e.message) }
  await new Promise((r) => setTimeout(r, 2500))
  const text = dom.window.document.body.textContent.replace(/\s+/g, ' ').trim()
  console.log(`\n=== ${route} (${errors.length} errors)\n${text.slice(0, 6000)}`)
  for (const e of errors.slice(0, 3)) console.log('  ! ' + e)
  for (const label of clicks) {
    const sel = label.startsWith('*') ? 'tr,button,a,div[draggable]' : 'button'
    const needle = label.replace(/^\*/, '')
    const els = [...dom.window.document.querySelectorAll(sel)].map((b) => [b, b.textContent.replace(/\s+/g, ' ').trim()])
    const btn = (els.find(([, t]) => t === needle) || els.find(([, t]) => t.startsWith(needle)) || [])[0]
    if (!btn) { console.log(`\n--- click "${label}": NOT FOUND`); continue }
    btn.dispatchEvent(new dom.window.MouseEvent('click', { bubbles: true, cancelable: true }))
    await new Promise((r) => setTimeout(r, 2000))
    const t = dom.window.document.body.textContent.replace(/\s+/g, ' ').trim()
    console.log(`\n--- after click "${label}" (${errors.length} errors)\n${t.slice(-3500)}`)
    for (const e of errors.slice(0, 3)) console.log('  ! ' + e)
  }
  dom.window.close()
}
