// End-to-end check of the SITE (Explore, Statistics, AI search) in a REAL browser, over the Chrome DevTools Protocol
// (no dependencies; Node >= 22). The questionnaire app at /app/ has its own run: tests/e2e/smoke.mjs.
//
//   node tests/e2e/site.mjs --base=http://127.0.0.1:8000 [--chrome="C:\Program Files\Google\Chrome\Application\chrome.exe"] [--out=shots] [--ai]
//
// It needs a running server (`python -m navigator.cli serve --mode live`) and Chrome or Edge. It checks the numbers on the
// Statistics page against the dataset the server publishes, opens a federal directory entry, and repeats the main pages on a 390px
// phone. `--ai` also sends one natural-language search through the real AI backend (a few model calls on the configured key).
// Exit code 1 on any failure or JavaScript error.
import { spawn } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

const args = Object.fromEntries(process.argv.slice(2).map((a) => { const [k, ...v] = a.replace(/^--/, '').split('='); return [k, v.join('=') || true]; }));
const BASE = args.base || 'http://127.0.0.1:8000';
const CHROME = args.chrome || 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe';
const OUT = args.out ? path.resolve(args.out) : '';
if (OUT) fs.mkdirSync(OUT, { recursive: true });

const results = [];
const check = (name, ok, detail = '') => { results.push({ name, ok: Boolean(ok) }); console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${ok || !detail ? '' : '  -> ' + detail}`); };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function launch() {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'ifn-site-'));
  const proc = spawn(CHROME, ['--headless=new', '--disable-gpu', '--no-first-run', '--no-default-browser-check', `--user-data-dir=${dir}`, '--remote-debugging-port=0', 'about:blank'], { stdio: ['ignore', 'ignore', 'pipe'] });
  const endpoint = await new Promise((resolve, reject) => {
    let buffer = '';
    proc.stderr.on('data', (d) => { buffer += d; const m = /DevTools listening on (ws:\/\/\S+)/.exec(buffer); if (m) resolve(m[1]); });
    setTimeout(() => reject(new Error('the browser did not start')), 20000);
  });
  return { proc, dir, endpoint };
}

class Cdp {
  constructor(url) { this.ws = new WebSocket(url); this.id = 0; this.pending = new Map(); this.listeners = []; }
  open() {
    return new Promise((resolve, reject) => {
      this.ws.onopen = resolve; this.ws.onerror = reject;
      this.ws.onmessage = (event) => {
        const msg = JSON.parse(event.data);
        if (msg.id && this.pending.has(msg.id)) { const { resolve: ok, reject: bad } = this.pending.get(msg.id); this.pending.delete(msg.id); if (msg.error) bad(new Error(msg.error.message)); else ok(msg.result); }
        else this.listeners.forEach((fn) => fn(msg));
      };
    });
  }
  send(method, params = {}, sessionId) {
    const id = ++this.id;
    this.ws.send(JSON.stringify({ id, method, params, sessionId }));
    return new Promise((resolve, reject) => this.pending.set(id, { resolve, reject }));
  }
}

async function newPage(cdp, { width, height, mobile }) {
  const { targetId } = await cdp.send('Target.createTarget', { url: 'about:blank' });
  const { sessionId } = await cdp.send('Target.attachToTarget', { targetId, flatten: true });
  const errors = [];
  cdp.listeners.push((msg) => {
    if (msg.sessionId !== sessionId) return;
    if (msg.method === 'Runtime.exceptionThrown') errors.push(msg.params.exceptionDetails.exception ? msg.params.exceptionDetails.exception.description : msg.params.exceptionDetails.text);
    if (msg.method === 'Runtime.consoleAPICalled' && msg.params.type === 'error') errors.push(msg.params.args.map((a) => a.value || a.description).join(' '));
    if (msg.method === 'Log.entryAdded' && msg.params.entry.level === 'error') errors.push(msg.params.entry.text + ' ' + (msg.params.entry.url || ''));
  });
  const send = (m, p) => cdp.send(m, p, sessionId);
  await Promise.all(['Page.enable', 'Runtime.enable', 'Log.enable'].map((m) => send(m)));
  await send('Emulation.setDeviceMetricsOverride', { width, height, deviceScaleFactor: mobile ? 2 : 1, mobile });
  const page = {
    errors,
    async go(url) { await send('Page.navigate', { url }); await sleep(900); },
    async eval(expression) {
      const r = await send('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true });
      if (r.exceptionDetails) throw new Error(r.exceptionDetails.exception ? r.exceptionDetails.exception.description : r.exceptionDetails.text);
      return r.result.value;
    },
    async waitFor(expression, what, timeout = 12000) {
      const t0 = Date.now();
      while (Date.now() - t0 < timeout) { try { if (await page.eval(expression)) return true; } catch { /* the page is still changing */ } await sleep(150); }
      throw new Error('timed out waiting for ' + what);
    },
    click: (selector) => page.eval(`(() => { const el = document.querySelector(${JSON.stringify(selector)}); if (!el) throw new Error('no element ' + ${JSON.stringify(selector)}); if (typeof el.click === 'function') el.click(); else el.dispatchEvent(new MouseEvent('click', { bubbles: true })); return true; })()`),
    async shot(name) {
      if (!OUT) return;
      // A page with hundreds of cards is taller than the browser can capture in one image ("Page is too large"): keep the top 8000 px.
      const height = await page.eval('document.documentElement.scrollHeight'), width = await page.eval('document.documentElement.clientWidth');
      const params = { format: 'png', captureBeyondViewport: true };
      if (height > 8000) params.clip = { x: 0, y: 0, width, height: 8000, scale: 1 };
      const { data } = await send('Page.captureScreenshot', params);
      fs.writeFileSync(path.join(OUT, name + '.png'), Buffer.from(data, 'base64'));
    },
  };
  return page;
}

const noSideScroll = (page) => page.eval('document.documentElement.scrollWidth <= window.innerWidth + 1');

async function statistics(page, expected, label) {
  await page.go(`${BASE}/#statistics`);
  await page.waitFor("document.querySelectorAll('#statistics-kpis .kpi').length === 5 && document.querySelectorAll('#canada-map path').length === 13", 'the Statistics page');
  await page.waitFor("document.querySelector('#stats-backend-status').textContent === 'Backend analytics'", 'the backend analytics');
  const kpis = await page.eval("Object.fromEntries([...document.querySelectorAll('.kpi')].map((x) => [x.querySelector('p').textContent, x.querySelector('.kpi-value').textContent]))");
  check(`${label}: KPIs show the records, the regions covered, nationwide and region-specific counts`, JSON.stringify([kpis.Opportunities, kpis['Regions covered'], kpis['National coverage'], kpis['Regional support']]) === JSON.stringify([String(expected.total), '13 / 13', String(expected.national), String(expected.regional)]), JSON.stringify(kpis));
  const buckets = await page.eval("[...document.querySelectorAll('#national-summary button')].map((x) => [x.querySelector('span').textContent, Number(x.querySelector('strong').textContent)])");
  check(`${label}: three region buckets that add up to the total`, JSON.stringify(buckets) === JSON.stringify([['Across Canada', expected.national], ['Region-specific', expected.regional], ['Region not stated', expected.unstated]]) && expected.national + expected.regional + expected.unstated === expected.total, JSON.stringify(buckets));
  const bars = await page.eval("[...document.querySelectorAll('#deadline-chart .chart-bar-label b')].map((x) => Number(x.textContent))");
  check(`${label}: the timing chart covers every record`, bars.length === 5 && bars.reduce((a, b) => a + b, 0) === expected.total, bars.join(','));
  check(`${label}: all 13 regions on the map and in the table`, (await page.eval("document.querySelectorAll('#region-table tbody tr').length")) === 13);
  // The map, as a person sees it.
  const regions = await page.eval('FundingModel.regions');
  const count = (code) => expected.records.filter((x) => x.province === regions[code]).length;
  const geo = await page.eval(`(() => { const out = {}; for (const k of ['YT', 'BC', 'NU', 'ON', 'QC', 'NS', 'NL']) { const r = document.querySelector('#canada-map path[data-region="' + k + '"]').getBoundingClientRect(); out[k] = { x: Math.round((r.left + r.right) / 2), y: Math.round((r.top + r.bottom) / 2) }; } return out; })()`);
  check(`${label}: the map has north at the top and west on the left`, geo.YT.y < geo.BC.y && geo.NU.y < geo.ON.y && geo.NS.y > geo.QC.y && geo.BC.x < geo.ON.x && geo.ON.x < geo.NL.x, JSON.stringify(geo));
  const fills = await page.eval("[...document.querySelectorAll('#canada-map path[data-region]')].map((p) => getComputedStyle(p).fill)");
  check(`${label}: every region is painted by its count (none is left at the empty colour)`, fills.length === 13 && fills.every((f) => f !== 'rgb(230, 236, 221)'), fills.join(' '));
  const marks = await page.eval("({ labels: [...document.querySelectorAll('#canada-map .map-label .map-count')].map((x) => Number(x.textContent)), chips: [...document.querySelectorAll('#canada-map .map-chip text')].map((x) => x.textContent) })");
  const wanted = Object.keys(regions).filter((c) => !['NB', 'NS', 'PE'].includes(c)).map(count).sort((a, b) => a - b);
  check(`${label}: the counts are written on the map (10 labels and 3 Atlantic chips)`, JSON.stringify([...marks.labels].sort((a, b) => a - b)) === JSON.stringify(wanted) && JSON.stringify(marks.chips.sort()) === JSON.stringify(['NB', 'NS', 'PE'].map((c) => `${c} ${count(c)}`).sort()), JSON.stringify(marks));
  const ranking = await page.eval("[...document.querySelectorAll('#region-ranking .ranking-list button')].map((x) => [x.querySelector('.rank-name').textContent, Number(x.querySelector('b').textContent)])");
  check(`${label}: the ranking lists all 13 regions with the dataset's counts, none empty`, ranking.length === 13 && ranking.every(([name, n]) => n > 0 && n === expected.records.filter((x) => x.province === name).length), JSON.stringify(ranking));
  await page.eval(`(() => { const p = document.querySelector('#canada-map path[data-region="MB"]'); const r = p.getBoundingClientRect(); p.dispatchEvent(new PointerEvent('pointerover', { bubbles: true, clientX: (r.left + r.right) / 2, clientY: (r.top + r.bottom) / 2 })); })()`);
  const tip = await page.eval(`(() => { const t = document.querySelector('#map-tooltip'); const s = document.querySelector('.map-stage').getBoundingClientRect(); const r = t.getBoundingClientRect(); return { hidden: t.hidden, text: t.innerText, inside: r.left >= s.left - 1 && r.right <= s.right + 1 && r.top >= s.top - 1 }; })()`);
  check(`${label}: hovering a region shows a card with its counts, inside the map`, !tip.hidden && tip.text.includes('Manitoba') && tip.text.includes(`${count('MB')} region-specific`) && tip.inside, JSON.stringify(tip));
  await page.shot(`${label}-statistics-hover`);
  await page.eval("document.querySelector('#canada-map').dispatchEvent(new PointerEvent('pointerleave'))");
  await page.click('[data-map-view="tiles"]');
  await page.waitFor("!document.querySelector('#tile-map').hidden", 'the tile map');
  const tiles = await page.eval("[...document.querySelectorAll('#tile-map .tile')].map((t) => [t.dataset.region, Number(t.querySelector('span').textContent), t.getBoundingClientRect().width])");
  check(`${label}: the tile map shows 13 readable tiles with the same counts`, tiles.length === 13 && tiles.every(([code, n, w]) => n === count(code) && w > 28), JSON.stringify(tiles));
  await page.shot(`${label}-statistics-tiles`);
  await page.click('[data-map-view="map"]');
  await page.waitFor("document.querySelector('#tile-map').hidden && !document.querySelector('#canada-map').hidden", 'the map again');
  check(`${label}: the page does not scroll sideways`, await noSideScroll(page));
  await page.shot(`${label}-statistics`);
}

async function main() {
  const data = await (await fetch(`${BASE}/data/opportunities.json`)).json();
  const records = data.records;
  const expected = {
    total: records.length,
    national: records.filter((x) => x.province === 'all').length,
    regional: records.filter((x) => x.province && x.province !== 'all').length,
    unstated: records.filter((x) => !x.province).length,
    records,
  };
  check('the server publishes the live dataset', data.data_mode === 'live' && records.length > 0, data.data_mode);

  const { proc, dir, endpoint } = await launch();
  const cdp = new Cdp(endpoint);
  await cdp.open();
  try {
    const desktop = await newPage(cdp, { width: 1280, height: 900, mobile: false });
    await desktop.go(`${BASE}/`);
    await desktop.waitFor("document.querySelector('#hero-title') && document.querySelector('#home-cards').children.length === 3", 'the home page');
    check('home loads with three preview cards and the live dataset', (await desktop.eval('document.body.dataset.dataMode')) === 'live');
    check('no demo wording on the home page', !/\b(Demo|Example data)\b/.test(await desktop.eval("document.querySelector('main').innerText + document.querySelector('.site-footer').innerText")));
    await desktop.shot('desktop-home');

    await statistics(desktop, expected, 'desktop');
    await desktop.click('#national-summary [data-value="unspecified"]');
    await desktop.waitFor(`document.querySelector('.kpi-value').textContent === ${JSON.stringify(String(expected.unstated))}`, 'the "not stated" selection');
    check('desktop: "Region not stated" narrows every chart to those records', (await desktop.eval("document.querySelectorAll('#amount-table-body tr').length")) === expected.unstated);
    await desktop.shot('desktop-statistics-not-stated');
    await desktop.click('#stats-clear-filters');
    await desktop.click('#canada-map [data-region="BC"]');
    await desktop.waitFor("document.querySelector('#quick-location').value === 'British Columbia'", 'the BC selection');
    const inBc = expected.national + records.filter((x) => x.province === 'British Columbia').length + expected.unstated;
    check('desktop: a map click selects the region; the KPI and the (40-row) table follow', (await desktop.eval("document.querySelector('.kpi-value').textContent")) === String(inBc) && (await desktop.eval("document.querySelectorAll('#amount-table-body tr').length")) === Math.min(40, inBc));
    await desktop.click('#stats-clear-filters');

    await desktop.go(`${BASE}/#explore`);
    await desktop.waitFor(`Number((document.querySelector('#results-count').textContent.match(/\\d+/) || ['0'])[0]) === ${expected.total}`, 'all records in Explore');
    check('desktop: Explore lists every record', true);
    const entry = records.find((x) => x.source_kind === 'directory_listing' && x.province === 'British Columbia');
    await desktop.eval(`document.querySelector('[data-detail=' + JSON.stringify(${JSON.stringify(entry.id)}) + ']').click()`);
    await desktop.waitFor("document.querySelector('#detail-dialog').open && document.querySelector('#detail-content').innerText.length > 200", 'the detail sheet');
    const detail = await desktop.eval("document.querySelector('#detail-content').innerText");
    check('desktop: a directory entry names the region basis and carries the Government of Canada statement', detail.includes('As listed in the federal directory') && detail.includes('published by Indigenous Services Canada') && detail.includes('endorsement of, the Government of Canada'), detail.slice(0, 120));
    check('desktop: the detail sheet says Published data, not Example data', detail.includes('Published data') && !detail.includes('Example'));
    await desktop.eval("document.querySelector('.detail-source').open = true");
    await desktop.shot('desktop-detail');
    check('desktop: no JavaScript errors', desktop.errors.length === 0, desktop.errors.join(' | ').slice(0, 300));

    if (args.ai) {
      await desktop.eval("document.querySelector('#detail-dialog').close()");
      await desktop.go(`${BASE}/#explore`);
      await desktop.waitFor("document.querySelector('#ai-connection-status').textContent.startsWith('AI connected')", 'the AI connection');
      check('desktop: the page reports the AI as connected', true);
      await desktop.eval("(() => { document.querySelector('#funding-search').value = 'I am a Metis student in BC looking for training support'; document.querySelector('#search-form').dispatchEvent(new Event('submit', {bubbles: true, cancelable: true})); return true; })()");
      await desktop.waitFor("!document.querySelector('#ai-search-summary').hidden && !document.querySelector('#search-submit').disabled", 'the AI answer', 90000);
      const summary = await desktop.eval("document.querySelector('#ai-search-summary').innerText");
      const shown = await desktop.eval(`Number((document.querySelector('#results-count').textContent.match(/\\d+/) || ['0'])[0])`);
      check('desktop: a natural-language search returns source-linked records through the real AI', /source-linked records/.test(summary) && shown >= 1 && shown <= 12, `${shown} shown; ${summary.slice(0, 140)}`);
      await desktop.shot('desktop-ai-search');
      check('desktop: no JavaScript errors after the AI search', desktop.errors.length === 0, desktop.errors.join(' | ').slice(0, 300));
    }

    const phone = await newPage(cdp, { width: 390, height: 844, mobile: true });
    await phone.go(`${BASE}/#explore`);
    await phone.waitFor("document.querySelectorAll('#results-grid .opportunity-card').length > 0", 'phone Explore');
    check('phone: Explore does not scroll sideways', await noSideScroll(phone));
    await phone.shot('phone-explore');
    await statistics(phone, expected, 'phone');
    check('phone: no JavaScript errors', phone.errors.length === 0, phone.errors.join(' | ').slice(0, 300));
  } finally {
    try { cdp.ws.close(); } catch { /* already closed */ }
    proc.kill();
    await sleep(300);
    fs.rmSync(dir, { recursive: true, force: true });
  }
  const failed = results.filter((r) => !r.ok);
  console.log(`${results.length - failed.length}/${results.length} checks passed`);
  process.exit(failed.length ? 1 : 0);
}

main().catch((error) => { console.error('FAIL  the run finished without an unexpected error  -> ' + error.message); process.exit(1); });
