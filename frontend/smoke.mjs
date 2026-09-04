// Offline UI smoke test: renders built routes in jsdom against a running API and prints visible text.
// Usage (from frontend/): TOKEN=<jwt> node smoke.mjs      (env: API, ROUTES, TOKEN)
import { JSDOM } from 'jsdom'
import fs from 'node:fs'
import path from 'node:path'

const dist = path.resolve('dist')
const html = fs.readFileSync(path.join(dist, 'index.html'), 'utf8')
const jsFile = fs.readdirSync(path.join(dist, 'assets')).find((f) => f.endsWith('.js'))
let bundle = fs.readFileSync(path.join(dist, 'assets', jsFile), 'utf8')
bundle = bundle.replace(/import\.meta\.url/g, '"http://localhost:5173/"').replace(/import\.meta\.resolve/g, '(function(x){return x})')
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
  try { dom.window.eval(bundle) } catch (e) { errors.push('eval: ' + e.message) }
  await new Promise((r) => setTimeout(r, 2500))
  const text = dom.window.document.body.textContent.replace(/\s+/g, ' ').trim()
  console.log(`\n=== ${route} (${errors.length} errors)\n${text.slice(0, 6000)}`)
  for (const e of errors.slice(0, 3)) console.log('  ! ' + e)
  for (const label of clicks) {
    const btn = [...dom.window.document.querySelectorAll('button')].find((b) => b.textContent.replace(/\s+/g, ' ').trim().startsWith(label))
    if (!btn) { console.log(`\n--- click "${label}": NOT FOUND`); continue }
    btn.dispatchEvent(new dom.window.MouseEvent('click', { bubbles: true, cancelable: true }))
    await new Promise((r) => setTimeout(r, 2000))
    const t = dom.window.document.body.textContent.replace(/\s+/g, ' ').trim()
    console.log(`\n--- after click "${label}" (${errors.length} errors)\n${t.slice(-3500)}`)
    for (const e of errors.slice(0, 3)) console.log('  ! ' + e)
  }
  dom.window.close()
}
