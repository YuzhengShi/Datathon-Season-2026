// Wires everything together: the state (in memory only), the hash router, and the "My list" dialog.
import * as api from './api.js';
import { announce, h, icon } from './dom.js';
import {
  SAMPLE_ANSWERS, buildProfile, defaultFilters, detailHash, isPersonalized, isoDate, joinRows, parseHash, rowFromDetail, shortlistText, withDeadlines,
} from './logic.js';
import { aboutView, errorView, loadingView, notFoundView, welcomeView } from './view_pages.js';
import { detailView } from './view_detail.js';
import { resultsView } from './view_results.js';
import { footer, header, listLabel } from './views_common.js';
import { wizardView } from './view_wizard.js';

const blank = () => ({ identity: [], fnRegistered: '', metisCitizen: '', inuitBeneficiary: '', province: '', level: '', studyStatus: '', school: '', otherSchoolName: '', otherSchoolProvince: '' });

// Nothing here is written to storage, cookies or the address bar: closing the tab forgets every answer.
const state = {
  answers: blank(), profile: {}, personalized: false, mode: 'none', // none | answers | browse | sample
  institutions: [], institutionsFailed: false, rows: null, excludedClosed: 0, lastChecked: '', today: isoDate(new Date()),
  filters: defaultFilters(), sort: 'best', shortlist: new Map(),
};
let current = null; // the page on screen, if it can repaint itself
let token = 0;      // a slow answer for a page the student already left is ignored

function paintCount() {
  for (const el of document.querySelectorAll('.js-list-count')) { el.textContent = String(state.shortlist.size); el.hidden = state.shortlist.size === 0; }
  for (const el of document.querySelectorAll('.js-list-button')) el.setAttribute('aria-label', listLabel(state.shortlist.size));
}

const ctx = {
  state, announce,
  nav(hash) { if (location.hash === hash) route(); else location.hash = hash; },
  savedCount: () => state.shortlist.size,
  isSaved: (id) => state.shortlist.has(id),
  toggleSave(row) { if (state.shortlist.has(row.id)) state.shortlist.delete(row.id); else state.shortlist.set(row.id, row); paintCount(); },
  onSearch(q) { state.filters.q = q; if (current && current.update) current.update(); },
  openList,
  finishWizard() { setAnswers('answers'); ctx.nav('#/results'); },
};

function setAnswers(mode) {
  state.mode = mode;
  state.profile = mode === 'browse' ? {} : buildProfile(state.answers, state.institutions);
  state.personalized = isPersonalized(state.profile);
  state.rows = null;
  state.filters = defaultFilters();
  state.sort = 'best';
}

async function ensureInstitutions() {
  if (state.institutions.length || state.institutionsFailed) return;
  try { state.institutions = (await api.getInstitutions()).institutions; } catch { state.institutionsFailed = true; }
}

async function ensureRows() {
  if (state.rows) return;
  const [list, match] = await Promise.all([api.getOpportunities(), api.postMatch(state.profile)]);
  state.today = isoDate(new Date());
  state.rows = withDeadlines(joinRows(list.results, match.results), state.today);
  state.excludedClosed = match.excluded_closed_count || 0;
  state.lastChecked = state.rows.map((r) => r.lastVerified).filter(Boolean).sort().pop() || '';
}

function mount(content, { search = false, title = '' } = {}) {
  const root = document.getElementById('root');
  root.replaceChildren(header(ctx, { search }), h('main', { id: 'main' }, content), footer(ctx));
  document.title = title ? `${title} - Funding Navigator` : 'Funding Navigator - scholarships for First Nations, Inuit and Métis students';
  window.scrollTo(0, 0);
  const heading = root.querySelector('#page-title');
  if (heading) heading.focus({ preventScroll: true });
}

async function useSample() {
  if (state.mode === 'sample') return;
  await ensureInstitutions();
  state.answers = { ...SAMPLE_ANSWERS, identity: [...SAMPLE_ANSWERS.identity] };
  setAnswers('sample');
}

async function showResults(r, mine) {
  if (r.params.sample) {
    await useSample();
  } else if (r.params.browse) {
    if (state.mode !== 'browse') { state.answers = blank(); setAnswers('browse'); }
  } else if (state.mode === 'none') {
    ctx.nav('#/start/1');
    return;
  }
  mount(loadingView(), { title: 'Loading' });
  try { await ensureRows(); } catch (error) { if (mine === token) mount(errorView(error, () => route()), { title: 'Problem' }); return; }
  if (mine !== token) return;
  const view = resultsView(ctx);
  current = view;
  mount(view.node, { search: true, title: 'Your results' });
}

async function showDetail(r, mine) {
  if (r.params.sample) await useSample();
  mount(loadingView(), { title: 'Loading' });
  try {
    const [detail] = await Promise.all([api.getDetail(r.id), state.mode === 'none' ? null : ensureRows()]);
    if (mine !== token) return;
    const row = (state.rows && state.rows.find((x) => x.id === r.id)) || rowFromDetail(detail, state.today);
    mount(detailView(ctx, row, detail), { title: row.title });
  } catch (error) {
    if (mine !== token) return;
    mount(error && error.status === 404 ? notFoundView() : errorView(error, () => route()), { title: 'Problem' });
  }
}

async function route() {
  const r = parseHash(location.hash);
  const mine = ++token;
  current = null;
  if (r.name === 'welcome') mount(welcomeView());
  else if (r.name === 'about') mount(aboutView(), { title: 'About' });
  else if (r.name === 'start') { await ensureInstitutions(); if (mine === token) mount(wizardView(ctx, r.step), { title: 'A few questions' }); }
  else if (r.name === 'results') await showResults(r, mine);
  else if (r.name === 'detail') await showDetail(r, mine);
  else mount(notFoundView(), { title: 'Not found' });
}

function copyText(text) {
  if (navigator.clipboard && window.isSecureContext) return navigator.clipboard.writeText(text);
  const box = h('textarea', { 'aria-hidden': 'true' }, text);
  document.body.append(box); box.select(); document.execCommand('copy'); box.remove();
  return Promise.resolve();
}

function openList() {
  const body = h('div', { class: 'dialog__body' });
  const copy = h('button', { class: 'btn btn--primary btn--small', type: 'button' }, icon('copy', 16), 'Copy as text');
  const dialog = h('dialog', { 'aria-label': 'My list' },
    h('div', { class: 'dialog__head' }, h('h2', {}, 'My list'), h('button', { class: 'btn btn--ghost btn--small', type: 'button', 'aria-label': 'Close my list', onClick: () => dialog.close() }, icon('x', 18))),
    body, h('div', { class: 'dialog__foot' }, copy,
      h('span', { class: 'small muted' }, 'Your list is kept only while this tab is open.')));
  const paint = () => {
    const rows = [...state.shortlist.values()];
    copy.disabled = rows.length === 0;
    body.replaceChildren(...(rows.length ? rows.map((r) => h('div', { class: 'list-item' },
      h('div', {}, h('strong', {}, h('a', { href: detailHash(r.id), onClick: () => dialog.close() }, r.title)),
        h('span', { class: 'muted small' }, `${r.provider} · ${r.amountView.text} · ${r.deadline.text}`)),
      h('button', { class: 'btn btn--ghost btn--small', type: 'button', 'aria-label': `Remove ${r.title} from my list`,
        onClick: () => { state.shortlist.delete(r.id); paintCount(); paint(); } }, icon('x', 16))))
      : [h('p', { class: 'muted' }, 'Nothing saved yet. Use “Save to my list” on any card.')]));
  };
  copy.addEventListener('click', async () => {
    await copyText(shortlistText([...state.shortlist.values()], state.today));
    copy.textContent = 'Copied';
    announce('Your list was copied');
  });
  dialog.addEventListener('close', () => { dialog.remove(); if (current && current.update) current.update(); else if (parseHash(location.hash).name === 'detail') route(); });
  document.body.append(dialog);
  paint();
  dialog.showModal();
}

window.addEventListener('hashchange', route);
route();
