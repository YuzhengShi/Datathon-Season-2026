// Checks the Streamlit version of the site (deploy/streamlit) in a real Chrome: it loads, its main paths work and, above all, it scrolls.
// Start the app first:  streamlit run deploy/streamlit/streamlit_app.py      (or give the address of the deployed app)
// Run:  node tests/e2e/streamlit.mjs --base=http://127.0.0.1:8501 [--out=shots]
// Needs Node.js 22+ and Chrome or Edge (set CHROME to the program if it is somewhere else).
import { spawn } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

const arg = (name, fallback) => (process.argv.find((a) => a.startsWith(`--${name}=`)) || '').slice(name.length + 3) || fallback;
const BASE = arg('base', 'http://127.0.0.1:8501');
const OUT = arg('out', '');
const CHROME = [process.env.CHROME, 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe', 'C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe', 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe', '/usr/bin/google-chrome', '/usr/bin/chromium', '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'].filter(Boolean).find((p) => fs.existsSync(p));
if (!CHROME) throw new Error('No Chrome or Edge found: set CHROME to its path.');
if (OUT) fs.mkdirSync(OUT, { recursive: true });

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const profile = fs.mkdtempSync(path.join(os.tmpdir(), 'streamlit-e2e-'));
const browser = spawn(CHROME, ['--headless=new', '--disable-gpu', '--no-first-run', '--no-default-browser-check', `--user-data-dir=${profile}`, '--remote-debugging-port=0', 'about:blank'], { stdio: ['ignore', 'ignore', 'pipe'] });
const endpoint = await new Promise((resolve, reject) => {
  let log = '';
  browser.stderr.on('data', (chunk) => { log += chunk; const found = /DevTools listening on (ws:\/\/\S+)/.exec(log); if (found) resolve(found[1]); });
  setTimeout(() => reject(new Error('The browser did not start.')), 20000);
});
const socket = new WebSocket(endpoint);
let nextId = 0;
const waiting = new Map();
const listeners = [];
await new Promise((resolve) => { socket.onopen = resolve; });
socket.onmessage = (event) => {
  const message = JSON.parse(event.data);
  if (message.id && waiting.has(message.id)) { waiting.get(message.id)(message.result ?? { error: message.error }); waiting.delete(message.id); } else if (message.method) listeners.forEach((fn) => fn(message));
};
const send = (method, params = {}, sessionId) => new Promise((resolve) => { const id = ++nextId; waiting.set(id, resolve); socket.send(JSON.stringify({ id, method, params, sessionId })); });

const results = [];
const check = (name, ok, detail = '') => { results.push(ok); console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${ok && !detail ? '' : '  -> ' + detail}`); };

// The code runs inside the page that holds the site, wherever that is: in a Streamlit component frame, or in that frame inside the frame of the host.
const site = (code) => `(async () => { const find = (doc) => { if (doc.querySelector('#home-view')) return doc.defaultView; for (const frame of doc.querySelectorAll('iframe')) { try { const found = find(frame.contentDocument); if (found) return found; } catch (error) { /* another origin */ } } return null; }; const w = find(document); if (!w) throw new Error('the site is not on the page yet'); const d = w.document, f = w.frameElement; ${code} })()`;

async function visit(label, { width, height, dpr, mobile }) {
  const { browserContextId } = await send('Target.createBrowserContext');
  const { targetId } = await send('Target.createTarget', { url: 'about:blank', browserContextId });
  const { sessionId } = await send('Target.attachToTarget', { targetId, flatten: true });
  const call = (method, params) => send(method, params, sessionId);
  const problems = [];
  listeners.push((m) => {
    if (m.sessionId !== sessionId) return;
    // Only what comes from the site and its adapter counts: the host page (Streamlit Community Cloud, for one) has errors of its own.
    const ours = (url) => !url || /\/component\//.test(url);
    if (m.method === 'Runtime.exceptionThrown' && ours(m.params.exceptionDetails.url)) problems.push('exception: ' + (m.params.exceptionDetails.exception?.description || m.params.exceptionDetails.text).slice(0, 160));
    if (m.method === 'Log.entryAdded' && m.params.entry.level === 'error' && ours(m.params.entry.url) && !/favicon|manifest/.test(m.params.entry.url || '')) problems.push('console: ' + m.params.entry.text.slice(0, 120));
    if (m.method === 'Network.responseReceived' && m.params.response.status >= 400 && /\/component\/|\/data\//.test(m.params.response.url)) problems.push(`HTTP ${m.params.response.status} ${m.params.response.url.slice(-70)}`);
  });
  await Promise.all(['Page.enable', 'Runtime.enable', 'Log.enable', 'Network.enable'].map((m) => call(m)));
  await call('Emulation.setDeviceMetricsOverride', { width, height, deviceScaleFactor: dpr, mobile });
  if (mobile) await call('Emulation.setTouchEmulationEnabled', { enabled: true, maxTouchPoints: 5 });
  const ev = async (expression) => { const r = await call('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true }); if (r.exceptionDetails) throw new Error((r.exceptionDetails.exception?.description || r.exceptionDetails.text).split('\n')[0]); return r.result?.value; };
  const waitFor = async (code, what, timeout = 90000) => { const t0 = Date.now(); let last = ''; while (Date.now() - t0 < timeout) { try { if (await ev(site(code))) return; } catch (error) { last = error.message; } if (Date.now() - t0 > 4000) await ev("[...document.querySelectorAll('button')].find((b) => /get this app back up/i.test(b.textContent))?.click()").catch(() => {}); await sleep(250); } throw new Error(`timed out waiting for ${what} (${last})`); };
  const shot = async (name) => { if (!OUT) return; const { data } = await call('Page.captureScreenshot', { format: 'jpeg', quality: 72 }); fs.writeFileSync(path.join(OUT, `${label}-${name}.jpg`), Buffer.from(data, 'base64')); };
  const gesture = async () => {
    if (mobile) {
      const x = Math.round(width / 2), from = Math.round(height * 0.75), to = Math.round(height * 0.25);
      await call('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: [{ x, y: from }] });
      for (let i = 1; i <= 12; i++) { await call('Input.dispatchTouchEvent', { type: 'touchMove', touchPoints: [{ x, y: Math.round(from + ((to - from) * i) / 12) }] }); await sleep(16); }
      await call('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] });
    } else await call('Input.dispatchMouseEvent', { type: 'mouseWheel', x: Math.round(width / 2), y: Math.round(height / 2), deltaX: 0, deltaY: 600 });
    await sleep(900);
  };

  await call('Page.navigate', { url: BASE });
  await waitFor("return d.readyState === 'complete' && Boolean(w.FundingModel);", 'the site');
  check(`${label}: the site loads inside the page`, true);
  await shot('home');

  await ev(site("w.location.hash = '#explore';"));
  await waitFor("return d.querySelectorAll('#results-grid .opportunity-card').length > 0;", 'the Explore list');
  await sleep(800);
  const explore = await ev(site("return { total: w.FundingModel.opportunities.length, count: d.querySelector('#results-count').textContent, hiddenAi: [...d.querySelectorAll('[data-assistant]')].every((e) => getComputedStyle(e).display === 'none'), mode: d.querySelector('#search-mode').value, fills: f ? Math.abs(f.getBoundingClientRect().height - w.parent.innerHeight) <= 2 : true, top: f ? Math.round(f.getBoundingClientRect().top) : 0 };"));
  check(`${label}: Explore lists every record`, explore.total > 0 && explore.count.includes(String(explore.total)), `${explore.count} of ${explore.total}`);
  check(`${label}: the AI entry points are hidden and search is keyword search`, explore.hiddenAi && explore.mode === 'keyword', JSON.stringify(explore));
  check(`${label}: the site fills the window`, explore.fills && explore.top <= 1, `top ${explore.top}`);
  await shot('explore');

  const keyword = await ev(site("const input = d.querySelector('#funding-search'); const before = d.querySelector('#results-count').textContent; input.value = 'Manitoba'; input.dispatchEvent(new Event('input', { bubbles: true })); await new Promise((r) => setTimeout(r, 500)); const after = d.querySelector('#results-count').textContent; input.value = ''; input.dispatchEvent(new Event('input', { bubbles: true })); return { before, after };"));
  check(`${label}: a keyword narrows the list`, keyword.before !== keyword.after, `${keyword.before} -> ${keyword.after}`);

  const detail = await ev(site("[...d.querySelectorAll('#results-grid [data-detail]')][0].click(); await new Promise((r) => setTimeout(r, 500)); const dialog = d.querySelector('#detail-dialog'); const save = [...dialog.querySelectorAll('button')].find((b) => /^\\s*Save/i.test(b.textContent)); const out = { open: dialog.open, save: Boolean(save) }; if (save) save.click(); await new Promise((r) => setTimeout(r, 300)); dialog.close(); return out;"));
  check(`${label}: a record opens its detail and can be saved`, detail.open && detail.save, JSON.stringify(detail));
  await ev(site("w.location.hash = '#saved'; await new Promise((r) => setTimeout(r, 600));"));
  const saved = await ev(site("return d.querySelectorAll('#results-grid .opportunity-card').length;"));
  check(`${label}: My saved holds the saved record`, saved === 1, `${saved} cards`);

  await ev(site("w.location.hash = '#statistics';"));
  await waitFor("return d.querySelectorAll('#canada-map path').length === 13;", 'the map', 30000);
  await sleep(700);
  const stats = await ev(site("const kpi = () => d.querySelector('#statistics-kpis .kpi-value').textContent; const before = kpi(); d.querySelector('#canada-map [data-region=\"BC\"]').dispatchEvent(new MouseEvent('click', { bubbles: true })); await new Promise((r) => setTimeout(r, 500)); return { before, after: kpi() };"));
  check(`${label}: Statistics draws the map and a click on BC narrows the numbers`, stats.before !== stats.after, `${stats.before} -> ${stats.after}`);
  await shot('statistics');

  for (const route of ['#home', '#explore', '#statistics']) {
    await ev(site(`w.location.hash = '${route}'; await new Promise((r) => setTimeout(r, 900)); w.scrollTo(0, 0);`));
    const scroller = "const moved = () => Math.max(d.body.scrollTop, d.documentElement.scrollTop, w.scrollY); return moved();";
    const before = await ev(site(scroller));
    await gesture();
    const after = await ev(site(scroller));
    check(`${label}: ${route.slice(1)} scrolls with ${mobile ? 'a swipe' : 'the mouse wheel'}`, after > before, `${before} -> ${after}`);
    if (route === '#home') await shot('home-scrolled');
  }
  const back = await ev(site("w.location.hash = '#statistics'; w.scrollTo(0, 400); await new Promise((r) => setTimeout(r, 300)); w.location.hash = '#explore'; await new Promise((r) => setTimeout(r, 900)); return Math.max(d.body.scrollTop, d.documentElement.scrollTop, w.scrollY);"));
  check(`${label}: a new page opens at the top`, back < 5, `${back}px`);

  check(`${label}: no errors and no missing files`, problems.length === 0, problems.slice(0, 5).join(' | '));
  await send('Target.closeTarget', { targetId });
}

try {
  await visit('desktop', { width: 1280, height: 800, dpr: 1, mobile: false });
  await visit('phone', { width: 390, height: 844, dpr: 2, mobile: true });
} catch (error) {
  check('the run finished', false, error.message);
} finally {
  socket.close();
  browser.kill();
  await sleep(300);
  fs.rmSync(profile, { recursive: true, force: true });
}
console.log(`\n${results.filter(Boolean).length}/${results.length} checks passed`);
if (results.some((ok) => !ok)) process.exitCode = 1;
