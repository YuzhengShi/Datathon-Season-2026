// End-to-end check of the web app in a REAL browser, driven over the Chrome DevTools Protocol (no dependencies; Node >= 22).
//
//   node tests/e2e/smoke.mjs --base=http://127.0.0.1:8000 [--chrome="C:\Program Files\Google\Chrome\Application\chrome.exe"] [--out=shots]
//
// It needs a running server (`python -m navigator.cli serve --mode live`) and Chrome or Edge. It clicks through the questionnaire,
// searches, filters, saves, opens the list, opens a detail page, and repeats the main pages on a 390px phone. Exit code 1 on any failure.
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
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'ifn-e2e-'));
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
    click: (selector) => page.eval(`(() => { const el = document.querySelector(${JSON.stringify(selector)}); if (!el) throw new Error('no element ' + ${JSON.stringify(selector)}); el.click(); return true; })()`),
    async setValue(selector, value) {
      await page.eval(`(() => { const el = document.querySelector(${JSON.stringify(selector)}); el.value = ${JSON.stringify(value)}; el.dispatchEvent(new Event('input', {bubbles: true})); el.dispatchEvent(new Event('change', {bubbles: true})); return true; })()`);
    },
    async shot(name) {
      if (!OUT) return;
      const { data } = await send('Page.captureScreenshot', { format: 'png', captureBeyondViewport: true });
      fs.writeFileSync(path.join(OUT, name + '.png'), Buffer.from(data, 'base64'));
    },
  };
  return page;
}

const text = (selector) => `((document.querySelector(${JSON.stringify(selector)}) || {}).textContent || '')`;
const count = (selector) => `Number((${text(selector)}.match(/\\d+/) || ['0'])[0])`;

async function desktop(cdp) {
  const page = await newPage(cdp, { width: 1280, height: 900, mobile: false });
  await page.go(`${BASE}/app/`);
  await page.waitFor(`${text('h1')}.includes('Find scholarships')`, 'the welcome page');
  check('welcome page shows the promise and a way to start', true);
  await page.click('a[href="#/start/1"]');
  await page.waitFor(`${text('legend')}.includes('Which of these describe you')`, 'question 1');
  check('the questionnaire starts with who the student is, and every question can be skipped', (await page.eval(text('.wizard__actions .btn--primary'))) === 'Skip');

  await page.click('input[name="identity"][value="first_nations"]');
  check('choosing an answer turns "Skip" into "Next"', (await page.eval(text('.wizard__actions .btn--primary'))) === 'Next');
  await page.click('.wizard__actions .btn--primary');
  await page.waitFor(`${text('legend')}.includes('status')`, 'the status question');
  await page.click('input[name="fnRegistered"][value="yes"]');
  await page.click('.wizard__actions .btn--primary');
  await page.waitFor(`${text('legend')}.includes('Where do you live')`, 'the residence question');
  await page.setValue('#province', 'BC');
  await page.click('.wizard__actions .btn--primary');
  await page.waitFor(`${text('legend')}.includes('studying')`, 'the study question');
  await page.click('input[name="level"][value="undergraduate"]');
  await page.click('input[name="studyStatus"][value="full_time"]');
  await page.click('.wizard__actions .btn--primary');
  await page.waitFor(`${text('legend')}.includes('Which school')`, 'the school question');
  await page.setValue('#school', 'sfu');
  check('the last question offers the results', (await page.eval(text('.wizard__actions .btn--primary'))) === 'Show my scholarships');
  await page.click('.wizard__actions .btn--primary');
  await page.waitFor(`document.querySelectorAll('.card').length > 5`, 'the results');

  const url = await page.eval('location.href');
  check('no answer is ever written into the address bar', !/first_nations|sfu|undergraduate|residence/i.test(url), url);
  check('the answers bar echoes the answers in plain words', (await page.eval(text('.answers-bar'))).includes('Simon Fraser University'));
  const total = await page.eval(count('.results__count'));
  check('results are listed like a store (cards with a price and a deadline)', await page.eval(`!!document.querySelector('.card .price') && !!document.querySelector('.card .deadline')`));
  await page.shot('results-desktop');

  await page.setValue('.search__input', 'nurs');
  await page.waitFor(`${count('.results__count')} < ${total}`, 'the search to narrow the list');
  check('search narrows the list', (await page.eval(text('.list'))).toLowerCase().includes('nurse'));
  await page.setValue('.search__input', '');
  await page.waitFor(`${count('.results__count')} === ${total}`, 'the search to clear');

  await page.click('.filters input[type="checkbox"]');
  await page.waitFor(`document.querySelectorAll('.chip--filter button').length > 0`, 'a filter chip');
  check('a filter shows up as a removable chip', true);
  await page.click('.chip--filter button');
  await page.waitFor(`${count('.results__count')} === ${total}`, 'the filter to clear');

  await page.setValue('#sort', 'amount');
  const prices = await page.eval(`[...document.querySelectorAll('.card .price')].slice(0, 4).map((e) => Number(((e.textContent.match(/\\$([\\d,]+)/) || [0, '0'])[1]).replace(/,/g, '')))`);
  check('sorting by amount puts the biggest first', prices[0] >= prices[1] && prices[1] >= prices[2], JSON.stringify(prices));

  await page.click('.card .btn--secondary');
  await page.waitFor(`${text('.js-list-count')} === '1'`, 'the list counter');
  check('saving a card updates "My list"', true);
  await page.click('.topbar__nav button');
  await page.waitFor(`!!document.querySelector('dialog[open] .list-item')`, 'the list dialog');
  check('"My list" opens a dialog with the saved item and a copy button', await page.eval(`!document.querySelector('dialog[open] .dialog__foot .btn--primary').disabled`));
  await page.click('dialog[open] .dialog__head button');
  await page.waitFor(`!document.querySelector('dialog[open]')`, 'the dialog to close');

  await page.click('.card .card__title a');
  await page.waitFor(`!!document.querySelector('.buybox')`, 'the detail page');
  check('a detail page has one h1, a buy box and safe external links', (await page.eval(`document.querySelectorAll('h1').length`)) === 1
    && await page.eval(`[...document.querySelectorAll('.buybox a[target="_blank"]')].every((a) => /noopener/.test(a.rel) && /noreferrer/.test(a.rel))`));
  check('the detail page says where the information comes from', (await page.eval(text('main'))).includes('Where this information comes from'));
  await page.shot('detail-desktop');

  await page.go(`${BASE}/app/#/results?browse=1`);
  await page.waitFor(`document.querySelectorAll('.card').length > 5`, 'the browse-everything results');
  await page.setValue('.search__input', 'Laura Finch');
  await page.waitFor(`${count('.results__count')} === 1`, 'the search for one award');
  await page.click('.card .card__title a');
  await page.waitFor(`!!document.querySelector('.buybox')`, 'the detail page of a shared-application award');
  check('an award that shares an application says so and links to the others',
    (await page.eval(text('main'))).includes('One application covers several awards') && (await page.eval(`document.querySelectorAll('.panel ul a[href^="#/s/"]').length`)) > 5);
  await page.shot('shared-application-desktop');
  check('a repeating deadline reads naturally', (await page.eval(text('.buybox'))).includes('Due every year on Apr 30'));  await page.go(`${BASE}/app/#/results?browse=1`);
  await page.waitFor(`document.querySelectorAll('.card').length > 0`, 'the browse-everything results');
  await page.setValue('.search__input', '');
  await page.waitFor(`document.querySelectorAll('.card').length > 5`, 'the full list again');
  await page.setValue('.search__input', 'PSSSP');
  await page.waitFor(`${count('.results__count')} === 1`, 'the search for the federal program');
  await page.click('.card .card__title a');
  await page.waitFor(`!!document.querySelector('.buybox')`, 'the detail page of a Government of Canada program');
  check('Government of Canada material carries the statement its reproduction terms require',
    (await page.eval(text('main'))).includes('not produced in affiliation with, or with the endorsement of, the Government of Canada'));
  // the clarification case: answer everything except "registered under the Indian Act", and the app asks for exactly that
  await page.go(`${BASE}/app/#/start/1`);
  await page.waitFor(`${text('legend')}.includes('Which of these describe you')`, 'question 1 again');
  await page.click('input[name="identity"][value="first_nations"]');
  await page.click('.wizard__actions .btn--primary');
  await page.waitFor(`${text('legend')}.includes('status')`, 'the status question again');
  await page.click('.wizard__actions .btn--primary');
  await page.waitFor(`${text('legend')}.includes('Where do you live')`, 'the residence question again');
  await page.setValue('#province', 'BC');
  await page.click('.wizard__actions .btn--primary');
  await page.waitFor(`${text('legend')}.includes('studying')`, 'the study question again');
  await page.click('input[name="level"][value="undergraduate"]');
  await page.click('input[name="studyStatus"][value="full_time"]');
  await page.click('.wizard__actions .btn--primary');
  await page.waitFor(`${text('legend')}.includes('Which school')`, 'the school question again');
  await page.setValue('#school', 'sfu');
  await page.click('.wizard__actions .btn--primary');
  await page.waitFor(`document.querySelectorAll('.card').length > 5`, 'the results after a skipped question');
  await page.setValue('.search__input', 'PSSSP');
  await page.waitFor(`${count('.results__count')} === 1`, 'the federal program again');
  check('a skipped question makes the card say that more answers would help', (await page.eval(text('.card'))).includes('More answers would help'));
  await page.click('.card .card__title a');
  await page.waitFor(`!!document.querySelector('.buybox')`, 'the detail page after a skipped question');
  const detail = await page.eval(text('main'));
  check('the detail page asks the exact question that was skipped, and says no card number is needed',
    detail.includes('Are you registered as a First Nations person under the Indian Act') && detail.includes('No card or registry number is needed'));
  check('nothing is stored in the browser (no cookies, local or session storage)', await page.eval(`document.cookie === '' && localStorage.length === 0 && sessionStorage.length === 0`));
  check('every button, field and link has an accessible name', await page.eval(`[...document.querySelectorAll('button, a[href], input, select')].every((el) => (el.textContent || '').trim() || el.getAttribute('aria-label') || (el.labels && el.labels.length) || el.closest('label'))`));
  check('no JavaScript errors on desktop', page.errors.length === 0, page.errors.slice(0, 3).join(' | '));
}

async function phone(cdp) {
  const page = await newPage(cdp, { width: 390, height: 844, mobile: true });
  for (const [name, hash] of [['welcome', ''], ['wizard', '#/start/4'], ['results', '#/results?sample=1']]) {
    await page.go(`${BASE}/app/${hash}`);
    await page.waitFor(`document.querySelector('h1, legend')`, `the ${name} page`);
    if (name === 'results') await page.waitFor(`document.querySelectorAll('.card').length > 5`, 'results on the phone');
    const [scroll, inner] = await page.eval(`[document.documentElement.scrollWidth, window.innerWidth]`);
    check(`no sideways scrolling on a 390px phone (${name})`, scroll <= inner + 1, `page is ${scroll}px wide in a ${inner}px window`);
    await page.shot(`${name}-phone`);
  }
  await page.click('.only-mobile');
  await page.waitFor(`!!document.querySelector('dialog[open] fieldset')`, 'the filter sheet');
  check('filters open as a sheet on the phone', await page.eval(`getComputedStyle(document.querySelector('.filters')).display === 'none'`));
  await page.click('dialog[open] .dialog__foot .btn--primary');
  const small = await page.eval(`[...document.querySelectorAll('button, a.btn, .choice, .check')].filter((el) => el.offsetParent !== null).filter((el) => el.getBoundingClientRect().height < 34).length`);
  check('touch targets are not tiny', small === 0, `${small} controls are shorter than 34px`);
  check('the top bar stays on two rows on a phone (brand and search), not three', await page.eval(`document.querySelector('.topbar').getBoundingClientRect().height <= 150`), 'the navigation wrapped onto its own row');
  const href = await page.eval(`document.querySelector('.card .card__title a').getAttribute('href')`);
  await page.go(`${BASE}/app/${href}?sample=1`);
  await page.waitFor(`!!document.querySelector('.buybox')`, 'the detail page on the phone');
  const [dScroll, dInner] = await page.eval(`[document.documentElement.scrollWidth, window.innerWidth]`);
  check('no sideways scrolling on a 390px phone (detail)', dScroll <= dInner + 1, `page is ${dScroll}px wide in a ${dInner}px window`);
  await page.shot('detail-phone');
  check('no JavaScript errors on the phone', page.errors.length === 0, page.errors.slice(0, 3).join(' | '));
}

const browser = await launch();
try {
  const cdp = new Cdp(browser.endpoint);
  await cdp.open();
  await desktop(cdp);
  await phone(cdp);
} catch (error) {
  check('the run finished without an unexpected error', false, error.message);
} finally {
  browser.proc.kill();
  await sleep(300);
  try { fs.rmSync(browser.dir, { recursive: true, force: true }); } catch { /* the browser may still hold a file */ }
}
const failed = results.filter((r) => !r.ok);
console.log(`\n${results.length - failed.length}/${results.length} checks passed`);
process.exit(failed.length ? 1 : 0);
