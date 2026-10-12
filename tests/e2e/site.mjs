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
    async mockFetch(source) { await send('Page.addScriptToEvaluateOnNewDocument', { source }); },
    async shotView(name) {
      if (!OUT) return;
      const { data } = await send('Page.captureScreenshot', { format: 'png' });
      fs.writeFileSync(path.join(OUT, name + '.png'), Buffer.from(data, 'base64'));
    },
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
  const timing = await page.eval("[...document.querySelectorAll('#deadline-chart .waffle-legend b')].map((x) => Number(x.textContent))");
  check(`${label}: the timing chart covers every record`, timing.length >= 1 && timing.reduce((a, b) => a + b, 0) === expected.total, timing.join(','));
  check(`${label}: all 13 regions on the map and in the table`, (await page.eval("document.querySelectorAll('#region-table tbody tr').length")) === 13);
  const report = await page.eval(`(() => ({ heat: document.querySelectorAll('.coverage-matrix tbody button').length, tiles: document.querySelectorAll('#deadline-chart .waffle-tile').length, treemap: document.querySelectorAll('#provider-treemap .treemap-cell').length, radial: document.querySelectorAll('#community-chart .radial-card').length, curve: Boolean(document.querySelector('#distribution-chart .cumulative-line')), median: document.querySelector('#distribution-metric strong').textContent }))()`);
  check(`${label}: the report charts (curve, heatmap, treemap, rings, timing tiles) are drawn from the records`, report.heat === 39 && report.tiles === Math.min(expected.total, 100) && report.treemap >= 2 && report.radial === 3 && report.curve && /^\$/.test(report.median), JSON.stringify(report));
  await page.eval("document.querySelector('.coverage-matrix').scrollIntoView({ block: 'center', behavior: 'instant' })");
  await sleep(250);
  await page.eval(`(() => { const b = document.querySelector('.coverage-matrix td button'); const r = b.getBoundingClientRect(); b.dispatchEvent(new PointerEvent('pointermove', { bubbles: true, clientX: r.left + r.width / 2, clientY: r.top + r.height / 2 })); })()`);
  const chartTip = await page.eval(`(() => { const t = document.querySelector('#chart-tooltip'), b = document.querySelector('.coverage-matrix td button').getBoundingClientRect(), r = t.getBoundingClientRect(); const px = b.left + b.width / 2, py = b.top + b.height / 2; return { hidden: t.hidden, text: t.innerText, dx: Math.round(r.left - Math.max(12, Math.min(innerWidth - r.width - 12, px + 12))), dy: Math.round(r.top - Math.max(12, Math.min(innerHeight - r.height - 12, py - r.height - 12))) }; })()`);
  check(`${label}: a heatmap tooltip opens at the pointer, not at the edge of its container`, !chartTip.hidden && chartTip.text.length > 10 && Math.abs(chartTip.dx) <= 2 && Math.abs(chartTip.dy) <= 2, JSON.stringify(chartTip));
  await page.eval("document.querySelector('#chart-tooltip').hidden = true; window.scrollTo(0, 0)");
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

// The chat ("Find a match"), with the model's answer replaced by real records from the dataset: it checks the layout, not the AI.
async function assistant(page, records, label) {
  const phone = label === 'phone';
  const unstated = records.filter((x) => !x.province);
  const picks = [...new Set([unstated[0], unstated[1], records.find((x) => x.province === 'British Columbia' && x.amount != null), records.find((x) => x.province === 'all'), records.reduce((a, b) => (b.provider.length > a.provider.length ? b : a)), records.find((x) => x.amount != null && !x.province)].filter(Boolean))].slice(0, 6);
  await page.mockFetch(`(() => {
    const realFetch = window.fetch.bind(window);
    const picks = ${JSON.stringify(picks)};
    const statuses = ['needs_provider_confirmation', 'potential_fit', 'needs_provider_confirmation', 'needs_information', 'needs_provider_confirmation', 'potential_fit'];
    const json = (value) => new Response(JSON.stringify(value), { status: 200, headers: { 'Content-Type': 'application/json' } });
    window.fetch = async (url, options) => {
      const target = String(url);
      if (target.endsWith('/api/health')) { const body = await (await realFetch(url, options)).json(); return json({ ...body, llm_ready: true }); }
      if (!target.endsWith('/api/conversation')) return realFetch(url, options);
      const results = picks.map((record, i) => ({ record, match: { match_status: statuses[i % statuses.length] }, reasons: ['Provider confirmation needed'] }));
      return json({ data_mode: FundingModel.mode, mode: 'match', intent: 'A Métis high-school student wants to know what funding is available for them.', message: results.length + ' records to explore. Confirm current requirements with each provider.', question: null, filters: FundingModel.toFilters({ community: 'Métis', location: 'British Columbia', goal: 'all', includeUnknown: true }), profile: { communities: ['Métis'], institution_province: 'British Columbia', education_level: 'high_school' }, results, statistics: null, tools_used: [{ name: 'find_matches', returned_records: results.length }] });
    };
  })();`);
  await page.go(`${BASE}/#explore`);
  await page.waitFor("document.querySelectorAll('#results-grid .opportunity-card').length > 0 && document.querySelector('#assistant-status').dataset.state === 'on'", `${label}: Explore and the chat connection`);
  await page.click('#explore-view [data-assistant="match"]');
  await page.waitFor("document.querySelector('#assistant-dialog').open", 'the chat dialog');
  const idle = await page.eval(`(() => ({ steps: document.querySelectorAll('#assistant-evidence-content .ev-steps li').length, empty: document.querySelectorAll('#assistant-evidence-content .ev-fact.is-empty').length, pill: document.querySelector('#assistant-status').textContent, welcome: Boolean(document.querySelector('.conversation-welcome h3')) }))()`);
  check(`${label}: before a question the chat shows a welcome, an empty profile and three steps`, idle.steps === 3 && idle.empty === 4 && idle.welcome && idle.pill === 'AI connected', JSON.stringify(idle));
  await page.shotView(`${label}-assistant-idle`);
  await page.eval(`(() => { document.querySelector('#conversation-input').value = 'I am a Metis high school student in Smithers and want to know what funding is available'; document.querySelector('#conversation-form').dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })); return true; })()`);
  await page.waitFor(`document.querySelectorAll('#conversation-thread .assistant-record').length === ${picks.length}`, 'the answer cards');
  await sleep(300);
  const m = await page.eval(`(() => {
    const q = (s) => document.querySelector(s), qa = (s) => [...document.querySelectorAll(s)];
    const box = q('#assistant-dialog').getBoundingClientRect(), side = q('.assistant-evidence'), thread = q('#conversation-thread'), cards = qa('#conversation-thread .assistant-record');
    const sideShown = getComputedStyle(side).display !== 'none';
    return {
      cards: cards.length,
      tallest: Math.round(Math.max(...cards.map((c) => c.getBoundingClientRect().height))),
      copies: qa('#assistant-evidence-content .assistant-record, #assistant-evidence-content [data-detail]').length,
      sideShown,
      facts: qa('.ev-fact').map((li) => li.innerText.split(String.fromCharCode(10)).join(' ').trim()),
      sources: qa('.ev-sources li').length,
      segments: qa('.ev-bar i').length,
      chips: qa('.answer-profile .ar-chip').length,
      chipsShown: Boolean(q('.answer-profile')) && getComputedStyle(q('.answer-profile')).display !== 'none',
      fit: qa('.ar-chip.is-fit').length,
      info: qa('.ar-chip.is-info').length,
      inside: box.left >= 0 && box.top >= 0 && box.right <= innerWidth + 1 && box.bottom <= innerHeight + 1,
      sideways: thread.scrollWidth > thread.clientWidth + 1 || (sideShown && side.scrollWidth > side.clientWidth + 1) || cards.some((c) => c.scrollWidth > c.clientWidth + 1),
    };
  })()`);
  check(`${label}: the answer is one compact card per record`, m.cards === picks.length && m.tallest <= (phone ? 170 : 150), JSON.stringify({ cards: m.cards, tallest: m.tallest }));
  check(`${label}: cards show the amount, the region and the fit as chips`, m.fit >= 1 && m.info >= 1, JSON.stringify({ fit: m.fit, info: m.info }));
  check(`${label}: the dialog fits the window and nothing in the chat scrolls sideways`, m.inside && !m.sideways, JSON.stringify({ inside: m.inside, sideways: m.sideways }));
  if (phone) check('phone: the side panel gives way to a row of profile chips inside the answer', !m.sideShown && m.chipsShown && m.chips >= 2, JSON.stringify({ sideShown: m.sideShown, chips: m.chips }));
  else check('desktop: the side panel summarises the answer (profile, where the matches apply, sources) and does not repeat the cards', m.sideShown && m.copies === 0 && m.facts.some((x) => x.includes('Community') && x.includes('Métis')) && m.facts.some((x) => x.includes('Region') && x.includes('British Columbia')) && m.sources >= 1 && m.segments >= 1, JSON.stringify(m.facts));
  await page.shotView(`${label}-assistant`);
  await page.click('#conversation-reset');
  await page.waitFor("document.querySelectorAll('#conversation-thread .assistant-record').length === 0 && document.querySelector('.conversation-welcome')", 'a new chat');
  check(`${label}: New chat in the header clears the answer`, true);
  await page.eval("document.querySelector('#assistant-dialog').close()");
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
    const chatDesktop = await newPage(cdp, { width: 1280, height: 820, mobile: false });
    await assistant(chatDesktop, records, 'desktop');
    check('desktop: no JavaScript errors in the chat', chatDesktop.errors.length === 0, chatDesktop.errors.join(' | ').slice(0, 300));

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
    const chatPhone = await newPage(cdp, { width: 390, height: 844, mobile: true });
    await assistant(chatPhone, records, 'phone');
    check('phone: no JavaScript errors in the chat', chatPhone.errors.length === 0, chatPhone.errors.join(' | ').slice(0, 300));
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
