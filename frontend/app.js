'use strict';

// Funding Navigator: the interface. The data comes from the service (api.js); every sentence a student reads about it is made in model.js.
const M = FundingModel;
const API = FundingApi;
const CONFIG = window.FN_CONFIG || {};
const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];
const esc = M.escapeHTML;
const icon = (name) => `<svg class="icon" aria-hidden="true"><use href="#i-${name}"/></svg>`;
// Opportunity ids contain colons and may contain anything else: look elements up by comparing, never by building a selector.
const byData = (attr, value, scope = document) => [...scope.querySelectorAll(`[${attr}]`)].find((el) => el.getAttribute(attr) === value);
const plural = (n, word) => `${n} ${word}${n === 1 ? '' : 's'}`;

const PAGE_SIZE = 24;
const SAVED_KEY = 'funding-navigator-saved';

const state = {
  phase: 'loading',               // loading | ready | error
  error: null,
  mode: 'live',                   // the service says whether this is real or made-up data
  institutions: [],
  list: [],                       // what /opportunities returned
  rows: [],                       // the list joined with the match for the current answers
  excludedClosed: 0,
  lastChecked: '',
  today: M.isoDate(new Date()),
  answers: M.blankAnswers(),      // nothing here is written to storage: reloading forgets every answer
  profile: {},
  personalized: false,
  query: '', type: 'all', amount: 'any', sort: 'best', layout: 'grid', showNo: false, page: 1,
  savedOnly: false,
  saved: [],                      // opportunity ids only
  bgView: '',                     // the page behind an open program
  programDepth: 0,                // history entries added by opening programs from inside the app
  detailRow: null,
  programIds: [],                 // the programs a reader can step through: the list behind the open dialog
  loading: null,
};

const matchCache = new Map();
const detailCache = new Map();
let matchToken = 0;
let detailToken = 0;
let toastTimer;
let previousView = '';
let detailOrigin = null;

// ---------------------------------------------------------------- saved list (ids only, on this device)
function loadSaved() {
  try {
    const values = JSON.parse(localStorage.getItem(SAVED_KEY) || '[]');
    if (Array.isArray(values)) state.saved = [...new Set(values.filter((v) => typeof v === 'string'))];
  } catch { /* storage is unavailable: the list lasts for this visit only */ }
}
const isSaved = (id) => state.saved.includes(id);
const savedRows = () => state.rows.filter((r) => isSaved(r.id));

// ---------------------------------------------------------------- data
function getMatch(profile) {
  const key = JSON.stringify(profile);
  if (!matchCache.has(key)) {
    const request = API.postMatch(profile);
    matchCache.set(key, request);
    request.catch(() => matchCache.delete(key));
  }
  return matchCache.get(key);
}

function getDetail(id) {
  if (!detailCache.has(id)) {
    const request = API.getDetail(id);
    detailCache.set(id, request);
    request.catch(() => detailCache.delete(id));
  }
  return detailCache.get(id);
}

function commitMatch(match) {
  state.rows = M.withDeadlines(M.joinRows(state.list, match.results), state.today);
  state.excludedClosed = match.excluded_closed_count || 0;
  state.lastChecked = M.lastCheckedOf(state.rows);
}

async function loadData() {
  state.phase = 'loading';
  state.error = null;
  renderAll();
  try {
    const [list, match, institutions] = await Promise.all([
      API.getOpportunities(),
      getMatch({}),
      API.getInstitutions().catch(() => ({ institutions: [] })), // the schools are a convenience: the list works without them
    ]);
    state.mode = list.data_mode || match.data_mode || 'live';
    state.institutions = institutions.institutions || [];
    state.list = list.results;
    state.today = M.isoDate(new Date());
    state.answers = M.blankAnswers();
    state.profile = {};
    state.personalized = false;
    commitMatch(match);
    state.phase = 'ready';
  } catch (error) {
    state.phase = 'error';
    state.error = error;
  }
  renderAll();
}

/** Change the answers: the service decides what fits, so a new answer means a new match. The old list stays until the new one arrives. */
async function applyAnswers(next) {
  const profile = M.buildProfile(next, state.institutions);
  const mine = ++matchToken;
  setBusy(true);
  try {
    const match = await getMatch(profile);
    if (mine !== matchToken) return false; // a newer change has already replaced this one
    state.answers = next;
    state.profile = profile;
    state.personalized = M.isPersonalized(profile);
    commitMatch(match);
    state.showNo = false;
    state.page = 1;
    return true;
  } catch {
    if (mine === matchToken) toast('We couldn’t update your matches. Please try again.');
    return false;
  } finally {
    if (mine === matchToken) {
      setBusy(false);
      renderAll();
    }
  }
}

function setBusy(busy) {
  const grid = $('#results-grid');
  grid.classList.toggle('is-busy', busy);
  grid.setAttribute('aria-busy', String(busy));
  if (busy) $('#results-count').textContent = 'Updating your matches…';
}

// ---------------------------------------------------------------- small pieces
const badge = (row) => `<span class="provider-badge ${row.badge.tone}" aria-hidden="true">${esc(row.badge.text)}</span>`;
const notice = (tone, glyph, html) => `<div class="notice notice-${tone}" role="note">${icon(glyph)}<p>${html}</p></div>`;
const savedCount = () => (state.phase === 'ready' ? savedRows().length : state.saved.length);

function saveButton(row, extraClass = '') {
  const saved = isSaved(row.id);
  return `<button class="save-button ${saved ? 'is-saved' : ''} ${extraClass}" data-save="${esc(row.id)}" aria-label="${saved ? 'Remove' : 'Save'} ${esc(row.title)}${saved ? ' from' : ' to'} My saved" aria-pressed="${saved}">${icon('bookmark')}</button>`;
}

function fitTag(row) {
  const glyph = { good: 'check', info: 'help', neutral: 'help', muted: 'close' }[row.fit.tone] || 'help';
  return `<span class="fit-tag fit-${row.fit.tone}">${icon(glyph)}${esc(row.fit.label)}</span>`;
}

function timingLine(row) {
  const d = row.deadline;
  const urgent = d.soon ? M.urgencyText(d.days) : '';
  return `<span class="card-timing${d.soon ? ' is-soon' : ''}">${icon('compass')}<span>${esc(d.text)}${urgent ? ` · ${esc(urgent)}` : ''}</span></span>`;
}

function card(row) {
  const parts = M.amountParts(row.amountView);
  const place = M.placeOf(row, state.institutions);
  const directory = row.source_kind === 'directory_listing';
  const when = ['open', 'upcoming', 'closed'].includes(row.availability) ? M.availabilityView(row.availability) : null;
  const tags = [
    row.communities.length ? `<span class="community-tag">${esc(row.communities.join(' · '))}</span>` : '',
    directory ? `<span class="source-tag" title="Taken from a federal directory, not from the provider’s own page">${icon('alert')}Government directory</span>` : '',
    when ? `<span class="status-tag status-${when.tone}">${esc(when.label)}</span>` : '',
    state.personalized ? fitTag(row) : '',
  ].join('');
  const meta = `${place ? `<span>${icon('pin')}<span>${esc(place)}</span></span>` : ''}${tags ? `<span class="card-tags">${tags}</span>` : ''}`;
  const muted = state.personalized && row.fit.key === 'no';
  return `<article class="opportunity-card${muted ? ' is-muted' : ''}"><div class="card-top">${badge(row)}<p class="card-provider" title="${esc(row.provider)}">${esc(M.clamp(row.provider, 58))}<span>${M.typeLabel(row)}</span></p>${saveButton(row)}</div><div class="card-content"><h2 class="card-title"><button data-detail="${esc(row.id)}">${esc(row.title)}</button></h2><div class="card-amount ${row.amountView.kind === 'unknown' ? 'is-unknown' : ''}">${esc(parts.figure)}<small>${esc(parts.note)}</small></div></div>${meta ? `<div class="card-meta">${meta}</div>` : ''}<div class="card-bottom">${timingLine(row)}<button class="card-link" data-detail="${esc(row.id)}">View details ${icon('arrow')}</button></div></article>`;
}

function previewCard(row) {
  const parts = M.amountParts(row.amountView);
  const place = M.placeOf(row, state.institutions);
  return `<article class="preview-card"><div class="preview-card-top">${badge(row)}${saveButton(row)}</div><h3><button data-detail="${esc(row.id)}">${esc(M.clamp(row.title, 72))}</button></h3><p class="preview-amount ${row.amountView.kind === 'unknown' ? 'is-unknown' : ''}">${esc(parts.figure)}</p><p class="preview-amount-note">${esc(parts.note)}</p><p class="preview-card-location">${esc(M.clamp(place || row.provider, 64))}</p><button class="preview-detail" data-detail="${esc(row.id)}">View details ${icon('arrow')}</button></article>`;
}

const skeletonCards = (n) => Array.from({ length: n }, () => '<article class="opportunity-card is-skeleton" aria-hidden="true"><i class="sk sk-badge"></i><i class="sk sk-line"></i><i class="sk sk-line short"></i><i class="sk sk-amount"></i><i class="sk sk-line"></i></article>').join('');

function errorText(error) {
  const base = error && error.message ? error.message : 'Something went wrong.';
  const hint = error && (error.status === 404 || error.kind === 'network')
    ? ' Open this page from the Funding Navigator server, which also provides the data, and check that it is running.' : '';
  return `${base}${hint} Nothing you entered has been lost or saved.`;
}

// ---------------------------------------------------------------- the page chrome
function renderStatus() {
  const tag = state.phase === 'ready' ? M.dataTag(state.mode, state.lastChecked) : state.phase === 'error' ? 'Not connected' : 'Loading…';
  $$('.js-data-tag').forEach((el) => { el.textContent = tag; });
}

function renderSavedCount() {
  const n = savedCount();
  $$('.save-count').forEach((el) => { el.textContent = n; el.hidden = n === 0; });
}

function renderHome() {
  const box = $('#home-cards');
  if (state.phase === 'loading') { box.innerHTML = [0, 1, 2].map(() => '<article class="preview-card is-skeleton" aria-hidden="true"><i class="sk sk-badge"></i><i class="sk sk-line"></i><i class="sk sk-amount"></i></article>').join(''); return; }
  if (state.phase === 'error') { box.innerHTML = '<p class="preview-note">The funding list could not be loaded just now.</p>'; return; }
  const top = M.sortRows(M.applyFilters(state.rows, M.defaultFilters(), state.personalized), 'best', state.personalized).slice(0, 3);
  box.innerHTML = top.length ? top.map(previewCard).join('') : '<p class="preview-note">No funding is listed right now.</p>';
}

// ---------------------------------------------------------------- the quick filters are windows onto the answers
let builtFor = null;

function locationOptionsHTML() {
  const byProvince = new Map();
  for (const school of state.institutions) {
    const key = school.province || '';
    if (!byProvince.has(key)) byProvince.set(key, []);
    byProvince.get(key).push(school);
  }
  const name = (code) => (code ? M.provinceName(code) : '');
  const groups = [...byProvince.entries()].sort((a, b) => name(a[0]).localeCompare(name(b[0])));
  return '<option value="">Study location</option>'
    + groups.map(([code, list]) => `<optgroup label="${esc(code ? 'Schools in ' + name(code) : 'Other schools')}">${list.map((s) => `<option value="school:${esc(s.id)}">${esc(s.name)}</option>`).join('')}</optgroup>`).join('')
    + `<optgroup label="Province or territory">${M.PROVINCES.map(([code, label]) => `<option value="prov:${code}">${esc(label)}</option>`).join('')}</optgroup>`;
}

function communityOptionsHTML() {
  const several = M.communityValue(state.answers) === 'multi';
  const label = (M.answerChips(state.answers, state.institutions).find((c) => c.key === 'identity') || {}).label || '';
  return `${several ? `<option value="multi">${esc(label)}</option>` : ''}<option value="">Community</option>${M.IDENTITIES.map(([value, text]) => `<option value="${value}">${esc(text)}</option>`).join('')}`;
}

const FILTER_DEFAULTS = { community: '', location: '', type: 'all', amount: 'any' };

/** Every filter that is narrowing the list, as a label a student can read and remove. */
function activeFilters() {
  const chips = M.answerChips(state.answers, state.institutions);
  const said = (key) => (chips.find((c) => c.key === key) || {}).label || '';
  const types = { award: 'Scholarships & awards', funding_channel: 'Funding programs' };
  const amounts = Object.fromEntries(M.AMOUNT_BUCKETS);
  const out = [];
  if (M.communityValue(state.answers)) out.push({ key: 'community', label: said('identity') });
  if (M.locationValue(state.answers)) out.push({ key: 'location', label: said('school') });
  if (state.type !== 'all') out.push({ key: 'type', label: types[state.type] || state.type });
  if (state.amount !== 'any') out.push({ key: 'amount', label: amounts[state.amount] || state.amount });
  for (const key of ['province', 'level', 'studyStatus']) if (said(key)) out.push({ key, label: said(key) }); // answers with no control of their own
  return out;
}

function renderFilters() {
  const where = $('#quick-location');
  if (builtFor !== state.institutions) { where.innerHTML = locationOptionsHTML(); builtFor = state.institutions; }
  const who = $('#quick-community');
  who.innerHTML = communityOptionsHTML();
  who.value = M.communityValue(state.answers);
  where.value = M.locationValue(state.answers);
  $('#quick-type').value = state.type;
  $('#quick-amount').value = state.amount;
  $('#funding-sort').value = state.sort;
  $$('[data-layout]').forEach((button) => {
    const selected = button.dataset.layout === state.layout;
    button.classList.toggle('active', selected);
    button.setAttribute('aria-pressed', String(selected));
  });
  const active = activeFilters();
  const box = $('#active-filters');
  box.hidden = active.length === 0;
  box.innerHTML = active.length
    ? `${state.personalized ? '<span>Your preferences</span>' : ''}${active.map((c) => `<button data-remove-filter="${esc(c.key)}" aria-label="Remove ${esc(c.label)} filter">${esc(c.label)} ${icon('close')}</button>`).join('')}` : '';
  $$('[data-filter]').forEach((el) => { el.closest('.select-field').classList.toggle('is-active', el.value !== FILTER_DEFAULTS[el.dataset.filter]); });
  $('.clear-filters').hidden = !(state.personalized || state.type !== 'all' || state.amount !== 'any' || state.query.trim());
}

// ---------------------------------------------------------------- the results
function currentFilters() {
  const f = M.defaultFilters();
  f.q = state.query;
  if (state.type !== 'all') f.type = new Set([state.type]);
  f.amount = state.amount;
  return f;
}

function renderNotices() {
  const notes = [];
  if (state.phase === 'ready' && state.mode === 'demo') {
    notes.push(notice('warn', 'alert', '<strong>Demo data.</strong> These scholarships are made up for testing. Do not use them to plan an application.'));
  }
  if (state.phase === 'ready' && state.excludedClosed && !state.savedOnly) {
    notes.push(notice('info', 'calendar', `${plural(state.excludedClosed, 'program')} closed to applications ${state.excludedClosed === 1 ? 'is' : 'are'} hidden.`));
  }
  if (state.phase === 'ready' && state.savedOnly) {
    const missing = state.saved.length - savedRows().length;
    if (missing > 0) notes.push(notice('info', 'info', `${plural(missing, 'saved item')} ${missing === 1 ? 'is' : 'are'} not listed right now. ${missing === 1 ? 'It' : 'They'} may have closed or been removed.`));
  }
  $('#results-notices').innerHTML = notes.join('');
}

/** What the list shows right now: the pool, the filters, the sort, and (once there are answers) without the ones that probably do not fit. */
function listing() {
  const pool = state.savedOnly ? savedRows() : state.rows;
  const showAll = state.showNo || state.savedOnly; // in My saved nothing is hidden: the student chose every one
  const filters = currentFilters();
  const visible = M.sortRows(M.applyFilters(pool, { ...filters, showNo: showAll }, state.personalized), state.sort, state.personalized);
  const hidden = showAll ? 0 : M.applyFilters(pool, { ...filters, showNo: true }, state.personalized).length - visible.length;
  return { visible, hidden };
}

function renderResults() {
  const grid = $('#results-grid');
  const empty = $('#empty-state');
  const more = $('#show-more');
  const toggle = $('[data-toggle-no]');
  $('#load-error').hidden = state.phase !== 'error';
  empty.hidden = true;
  more.hidden = true;
  toggle.hidden = true;
  renderNotices();
  if (state.phase === 'error') {
    $('#load-error-text').textContent = errorText(state.error);
    grid.hidden = true;
    grid.innerHTML = '';
    $('#results-count').textContent = '';
    return;
  }
  grid.hidden = false;
  grid.classList.remove('is-busy');
  if (state.phase === 'loading') {
    grid.classList.remove('list-layout');
    grid.innerHTML = skeletonCards(6);
    $('#results-count').textContent = 'Loading funding…';
    return;
  }
  const { visible, hidden } = listing();
  const shown = visible.slice(0, state.page * PAGE_SIZE);

  grid.classList.toggle('list-layout', state.layout === 'list');
  grid.innerHTML = shown.map(card).join('');
  grid.hidden = visible.length === 0;
  empty.hidden = visible.length !== 0;
  $('#results-count').innerHTML = `${state.savedOnly ? 'Saved opportunities' : 'Opportunities'} <strong>${visible.length}</strong>${shown.length < visible.length ? ` <span class="results-shown">· showing ${shown.length}</span>` : ''}`;
  if (shown.length < visible.length) {
    const left = visible.length - shown.length;
    more.hidden = false;
    more.firstElementChild.textContent = `Show ${Math.min(PAGE_SIZE, left)} more · ${left} left`;
  }
  if (state.personalized && !state.savedOnly && (hidden > 0 || state.showNo)) {
    toggle.hidden = false;
    toggle.textContent = state.showNo ? 'Hide ones I probably don’t qualify for' : `Also show ${hidden} I probably don’t qualify for`;
  }

  const nothingListed = state.rows.length === 0;
  const noSaved = state.savedOnly && state.saved.length === 0;
  $('#empty-title').textContent = nothingListed ? 'No funding is listed right now.' : noSaved ? 'Your next steps belong here.' : 'No opportunities found.';
  $('#empty-description').textContent = nothingListed ? 'Please check back soon.' : noSaved ? 'Save an opportunity to find it here later.' : 'Try another search or adjust your filters.';
  $('#reset-results').hidden = nothingListed;
  $('#reset-results').innerHTML = noSaved ? `Explore funding ${icon('arrow')}` : `Reset filters ${icon('arrow')}`;
  $('#explorer-title').textContent = state.savedOnly ? 'My saved' : 'Explore funding';
  $('#explorer-description').textContent = state.savedOnly ? 'Your next steps, in one place.' : 'Find support for your next chapter.';
}

// ---------------------------------------------------------------- the profile page
function renderProfile() {
  const a = state.answers;
  const chips = M.answerChips(a, state.institutions);
  const said = (key) => (chips.find((c) => c.key === key) || {}).label || '';
  const main = [['Community', said('identity')], ['Study location', said('school')], ['Study plans', M.planLabel(a)]];
  const more = [
    ['Lives in', a.province ? M.provinceName(a.province) : ''],
    ['Full-time or part-time', a.studyStatus === 'full_time' ? 'Full-time' : a.studyStatus === 'part_time' ? 'Part-time' : ''],
    ...M.statusAnswers(a).map((s) => [s.label, s.value]),
  ].filter(([, value]) => value);
  const rows = [...main, ...more];
  const any = rows.some(([, value]) => value);
  $('#profile-content').innerHTML = `<div class="profile-heading"><span>${icon('user')}</span><div><h2>Your preferences</h2><p>Optional questions, for this visit.</p></div></div><dl class="profile-list">${rows.map(([label, value]) => `<div><dt>${esc(label)}</dt><dd class="${value ? '' : 'unset'}">${esc(value || 'Not set')}</dd></div>`).join('')}</dl><div class="profile-actions"><button class="button ${any ? 'button-outline' : ''}" data-quiz>${any ? 'Edit preferences' : 'Set my preferences'} ${icon('arrow')}</button>${any ? `<button class="button" data-use-profile>Explore my matches ${icon('spark')}</button>` : ''}</div>${any ? '<button class="profile-clear text-link" data-clear-profile>Clear preferences</button>' : ''}`;
}

function renderAll() {
  renderStatus();
  renderSavedCount();
  renderHome();
  renderFilters();
  renderResults();
  renderProfile();
}

// ---------------------------------------------------------------- one program
const RULE_ICON = { pass: 'check', fail: 'close', unknown: 'help', ask: 'info' };
const RULE_WORD = { pass: 'Matches your answers', fail: 'Does not match your answers', unknown: 'Needs confirming', ask: 'Asked by the provider' };

function criteria(items) {
  return `<div class="program-criteria">${items.map((i) => `<div class="program-criterion is-${i.kind}"><span>${icon(RULE_ICON[i.kind])}</span><div><small>${esc(i.label)}</small><p><span class="sr-only">${esc(RULE_WORD[i.kind])}: </span>${esc(i.text)}</p>${i.why ? `<p class="criterion-why">${esc(i.why)}</p>` : ''}</div></div>`).join('')}</div>`;
}

function stepLink(url) {
  const safe = M.safeUrl(url);
  return safe ? `<a class="step-link" href="${esc(safe)}" target="_blank" rel="noopener noreferrer">Open the page ${icon('arrow-up')}</a>` : '';
}

function sharedBlock(siblings) {
  const shown = siblings.slice(0, 10);
  return `<div class="program-shared"><h4 class="program-subhead">One application covers several awards</h4><p>The provider uses the same application for ${plural(siblings.length, 'other award')}. Apply once; each award still has its own conditions, so read them.</p><ul class="program-list">${shown.map((s) => `<li><button class="text-link" data-detail="${esc(s.id)}">${esc(s.title)}</button></li>`).join('')}</ul>${siblings.length > shown.length ? `<p class="program-note">and ${siblings.length - shown.length} more</p>` : ''}</div>`;
}

function overviewPanel(row, detail) {
  const lead = row.source_kind === 'directory_listing' ? M.cardSummary(row) : row.summary;
  const statements = M.providerStatements(detail);
  const words = M.amountWords(row.amount);
  const siblings = detail.shared_application_with || [];
  const notes = [...new Set([...row.funderConditions.map((c) => c.text || c.rule || ''), ...M.visibleFlags(row.flags).map(M.flagText)].filter(Boolean))];
  const when = ['open', 'upcoming', 'closed'].includes(row.availability) ? M.availabilityView(row.availability) : null;
  const tags = [
    when ? `<span>${icon('calendar')}${esc(when.label)}</span>` : '',
    state.personalized ? `<span>${icon('check')}${esc(row.fit.label)}</span>` : '',
    siblings.length ? `<span>${icon('book')}Shared application</span>` : '',
  ].join('');
  return `<section class="program-panel" id="program-panel-overview" data-program-panel="overview" role="tabpanel" aria-labelledby="program-tab-overview" tabindex="0"><h3>About this funding</h3>${lead ? `<p>${esc(lead)}</p>` : '<p>The provider’s page does not give a summary.</p>'}${words ? `<p class="program-note"><strong>The amount, in the provider’s words:</strong> “${esc(words)}”</p>` : ''}${statements.length ? `<h4 class="program-subhead">In the provider’s words</h4><ul class="program-list">${statements.map((s) => `<li>${esc(s)}</li>`).join('')}</ul>` : ''}${tags ? `<div class="program-study-tags">${tags}</div>` : ''}${siblings.length ? sharedBlock(siblings) : ''}${notes.length ? `<h4 class="program-subhead">Good to know</h4><ul class="program-list">${notes.map((n) => `<li>${esc(n)}</li>`).join('')}</ul>` : ''}</section>`;
}

function eligibilityPanel(row, detail) {
  let body;
  if (state.personalized) {
    const items = M.ruleItems(row, state.institutions);
    body = `<h3>How you match</h3><p><strong>${esc(row.fit.label)}.</strong> This compares your answers with what the provider has published. It is not a prediction of whether you would receive the funding.</p>${items.length ? criteria(items) : '<p>The provider has not published conditions we can check. Ask them who is eligible.</p>'}${row.questions.length ? `<h4 class="program-subhead">Answer these to improve the match</h4><ul class="program-list">${row.questions.map((q) => `<li>${esc(q)}</li>`).join('')}</ul>` : ''}<button class="button button-outline button-small program-cta" data-quiz>${icon('spark')}Edit my preferences</button>`;
  } else {
    const items = M.requirementList(row, detail, state.institutions);
    body = `<h3>What the provider asks for</h3>${items.length ? criteria(items) : '<p>The provider does not list requirements we can read automatically.</p>'}<p class="program-criteria-note">These are the conditions as the provider published them. Confirm all requirements with the provider.</p><button class="button button-outline button-small program-cta" data-quiz>${icon('spark')}Find my matches</button>`;
  }
  return `<section class="program-panel" id="program-panel-eligibility" data-program-panel="eligibility" role="tabpanel" aria-labelledby="program-tab-eligibility" tabindex="0" hidden>${body}</section>`;
}

function stepsPanel(row, detail) {
  const steps = M.nextSteps(row, detail);
  return `<section class="program-panel" id="program-panel-steps" data-program-panel="steps" role="tabpanel" aria-labelledby="program-tab-steps" tabindex="0" hidden><h3>Your next steps</h3><ol class="program-next-steps">${steps.map((s, index) => `<li><span aria-hidden="true">0${index + 1}</span><div><h4>${esc(s.title)}</h4><p>${esc(s.text)}</p>${stepLink(s.url)}</div></li>`).join('')}</ol></section>`;
}

function sourceDetails(row, quotes) {
  const s = M.sourceView(row);
  const checked = row.lastVerified ? ` Last checked ${esc(M.plainDate(row.lastVerified))}.` : '';
  const quoteList = quotes.slice(0, 8).map((q) => {
    const link = M.safeUrl(q.url);
    return `<blockquote class="program-quote"><p>“${esc(q.quote)}”</p><footer>${esc(q.label)}${q.heading ? ` · under “${esc(q.heading)}”` : ''}${link ? ` · <a href="${esc(link)}" target="_blank" rel="noopener noreferrer">open the page</a>` : ''}</footer></blockquote>`;
  }).join('');
  return `<details class="detail-source"><summary>Source & current details ${icon('chevron')}</summary><div class="source-note source-${s.tone}">${icon(s.tone === 'warn' ? 'alert' : 'shield')}<p><strong>${esc(s.label)}.</strong> ${esc(s.note)}</p></div>${quotes.length ? `<h4 class="program-subhead">What the page says</h4>${quoteList}` : ''}<p>A computer read this page and checked that every quote above appears on it. A person has not reviewed it yet, so always confirm on the provider’s page.${checked}</p><p>Filters and matches show a starting point. Confirm eligibility, available funding and dates with the provider.</p></details>`;
}

function programActions(row) {
  const route = row.route || {};
  const official = M.safeUrl(row.officialUrl);
  const apply = M.safeUrl(route.url) || official;
  const label = route.route_type === 'contact_administrator' ? 'See how to apply' : route.route_type === 'online_application' ? 'Go to the application' : 'Visit provider';
  const saved = isSaved(row.id);
  return `${apply ? `<a class="button button-light" href="${esc(apply)}" target="_blank" rel="noopener noreferrer">${label} ${icon('arrow-up')}</a>` : ''}<button class="button button-outline" data-save="${esc(row.id)}" aria-pressed="${saved}" aria-label="${saved ? 'Remove' : 'Save'} ${esc(row.title)}${saved ? ' from' : ' to'} My saved">${icon('bookmark')}${saved ? 'Saved' : 'Save'}</button>`;
}

function detailHighlights(row) {
  const parts = M.amountParts(row.amountView);
  const d = row.deadline;
  const urgent = d.soon ? M.urgencyText(d.days) : '';
  const place = M.placeOf(row, state.institutions);
  const loose = row.amountView.kind === 'unknown' || row.amountView.kind === 'variable';
  return `<dl class="program-highlights"><div class="funding-highlight"><dt>Funding</dt><dd class="program-amount${loose ? ' varies' : ''}">${esc(parts.figure)}<small>${esc(parts.note)}</small></dd></div><div><dt>${icon('compass')}When to apply</dt><dd>${esc(d.text)}<small>${esc(urgent || d.detail || 'Confirm the current cycle')}</small></dd></div><div><dt>${icon('pin')}Study location</dt><dd>${esc(place || 'Not specified')}</dd></div></dl>`;
}

function detailAside(row, detail) {
  const art = M.artFor(row);
  const step = M.nextSteps(row, detail)[0];
  const official = M.safeUrl(row.officialUrl);
  const quiet = 'Not specified';
  const plans = M.plansOf(row);
  return `<aside class="program-aside" aria-label="Application and program attributes"><div class="program-summary"><div class="program-action-heading"><p class="support-label">Your next step</p><figure class="program-illustration ${art.tone}"><img src="assets/illustrations/${art.asset}.png" width="1254" height="1254" alt="" decoding="async"></figure></div><h3>${esc(step.title)}</h3><p class="program-action-note">${esc(step.text)}</p><div class="program-desktop-actions">${programActions(row)}</div>${official ? `<p class="program-source-link">${icon('shield')}Source <a href="${esc(official)}" target="_blank" rel="noopener noreferrer">${esc(M.hostOf(official))}</a></p>` : ''}</div><dl class="program-attributes"><div><dt>Community</dt><dd>${esc(row.communities.length ? row.communities.join(' · ') : quiet)}</dd></div><div><dt>Study plans</dt><dd>${esc(plans.length ? plans.join(' · ') : quiet)}</dd></div><div><dt>Program type</dt><dd>${esc(M.typeLabel(row))}</dd></div></dl></aside>`;
}

function detailToolbar(id) {
  const back = state.bgView === 'home' ? 'Back to preview' : state.bgView === 'saved' ? 'Back to My saved' : 'Back to funding';
  const tag = state.phase === 'ready' ? M.dataTag(state.mode, state.lastChecked) : '';
  const at = state.programIds.indexOf(id);
  const last = state.programIds.length - 1;
  const nav = at >= 0
    ? `<nav class="program-record-nav" aria-label="Browse current opportunities"><button class="icon-button record-previous" data-program-move="-1" aria-label="Previous program" ${at === 0 ? 'disabled' : ''}>${icon('arrow')}</button><span>${at + 1} <span aria-hidden="true">/</span> ${last + 1}</span><button class="icon-button" data-program-move="1" aria-label="Next program" ${at === last ? 'disabled' : ''}>${icon('arrow')}</button></nav>` : '';
  return `<header class="program-toolbar"><button class="program-back" data-close>${icon('arrow')}${back}</button><div class="program-toolbar-right">${nav}${tag ? `<span class="demo-tag js-data-tag">${esc(tag)}</span>` : ''}<button class="icon-button" data-close aria-label="Close program details">${icon('close')}</button></div></header>`;
}

function renderDetail(row, detail) {
  const tab = (value, label, selected) => `<button id="program-tab-${value}" type="button" role="tab" data-program-tab="${value}" aria-controls="program-panel-${value}" aria-selected="${selected}" tabindex="${selected ? '0' : '-1'}">${label}</button>`;
  const source = M.sourceView(row);
  const quotes = M.evidenceList(row, detail);
  const gov = M.governmentAttribution(row, quotes);
  const warn = row.source_kind === 'directory_listing' ? notice('warn', 'alert', '<strong>Check the details with the provider.</strong> This comes from a government directory that can be many years old. It lists no deadline.') : '';
  return `${detailToolbar(row.id)}<div class="program-scroll"><div class="program-heading"><div class="program-provider">${badge(row)}<span>${esc(row.provider)}${row.donor ? ` · funded by ${esc(row.donor)}` : ''}<small>${esc(M.typeLabel(row))} · ${esc(source.label)}${source.year ? ` · ${esc(source.year)}` : ''}</small></span></div><h2 id="detail-title" tabindex="-1">${esc(row.title)}</h2></div>${detailHighlights(row)}<div class="program-layout"><section class="program-main">${warn}<div class="program-tabs" role="tablist" aria-label="Program information">${tab('overview', 'Overview', true)}${tab('eligibility', 'Who it’s for', false)}${tab('steps', 'Next steps', false)}</div>${overviewPanel(row, detail)}${eligibilityPanel(row, detail)}${stepsPanel(row, detail)}${sourceDetails(row, quotes)}${gov ? `<p class="attribution">${esc(gov)}</p>` : ''}</section>${detailAside(row, detail)}</div></div><footer class="program-mobile-actions">${programActions(row)}</footer>`;
}

const detailLoading = (id) => `${detailToolbar(id)}<div class="program-scroll"><div class="program-loading" aria-busy="true"><h2 id="detail-title" class="sr-only" tabindex="-1">Loading</h2><i class="sk sk-badge"></i><i class="sk sk-title"></i><i class="sk sk-line"></i><i class="sk sk-line short"></i><i class="sk sk-block"></i></div></div>`;

function detailProblem(error, id) {
  const missing = error && error.status === 404;
  return `${detailToolbar()}<div class="program-scroll"><div class="program-problem"><h2 id="detail-title" tabindex="-1">${missing ? 'We couldn’t find that opportunity.' : 'We couldn’t load this opportunity.'}</h2><p>${missing ? 'It may have closed or been removed.' : esc(errorText(error))}</p><button class="button" data-close>${icon('arrow')}Back</button></div></div>`;
}

function setProgramTab(value, focus = false) {
  if (!['overview', 'eligibility', 'steps'].includes(value)) return;
  $$('[data-program-tab]').forEach((button) => {
    const selected = button.dataset.programTab === value;
    button.setAttribute('aria-selected', String(selected));
    button.setAttribute('tabindex', selected ? '0' : '-1');
    if (selected && focus) button.focus({ preventScroll: true });
  });
  $$('[data-program-panel]').forEach((panel) => { panel.hidden = panel.dataset.programPanel !== value; });
}

// A program has an address (#program/<id>), so a link to it can be shared and the Back button closes it.
function rememberOrigin(id) {
  const scope = document.activeElement && document.activeElement.closest('#home-view, #explore-view');
  detailOrigin = { id, scope: scope ? scope.id : '' };
  state.programIds = programList().map((r) => r.id);
}

/** The programs a reader can step through with the arrows: the list that is showing behind the dialog. */
function programList() {
  if (state.bgView === 'home') return M.sortRows(M.applyFilters(state.rows, M.defaultFilters(), state.personalized), 'best', state.personalized);
  return listing().visible;
}

function moveProgram(direction) {
  const current = M.parseRoute(location.hash);
  if (![-1, 1].includes(direction) || current.view !== 'program') return;
  const index = state.programIds.indexOf(current.id) + direction;
  if (index < 0 || index >= state.programIds.length) return;
  location.replace(M.programHash(state.programIds[index])); // stepping through programs keeps one place in the history
}

function openProgram(id) {
  const hash = M.programHash(id);
  if (location.hash === hash) { route(); return; }
  if ($('#detail-dialog').open) {
    location.replace(hash); // from one award to another that shares its application: the same place in the history
  } else {
    state.programDepth = 1;
    location.hash = hash;
  }
}

async function showProgram(id) {
  const dialog = $('#detail-dialog');
  const content = $('#detail-content');
  const mine = ++detailToken;
  if (!dialog.open) dialog.showModal();
  content.innerHTML = detailLoading(id);
  try {
    await state.loading;
    if (!state.programIds.length) state.programIds = programList().map((r) => r.id);
    if (!state.programIds.includes(id)) state.programIds = [id];
    const detail = await getDetail(id);
    if (mine !== detailToken) return;
    const row = state.rows.find((r) => r.id === id) || M.rowFromDetail(detail, state.today);
    state.detailRow = row;
    content.innerHTML = renderDetail(row, detail);
    document.title = `${row.title} — Funding Navigator`;
    $('.program-scroll').scrollTop = 0;
    $('#detail-title').focus({ preventScroll: true });
  } catch (error) {
    if (mine !== detailToken) return;
    state.detailRow = null;
    content.innerHTML = detailProblem(error, id);
  }
}

function onDetailClosed() {
  detailToken += 1; // a late answer must not repaint a closed dialog
  state.detailRow = null;
  state.programIds = [];
  const origin = detailOrigin;
  detailOrigin = null;
  if (M.parseRoute(location.hash).view === 'program') {
    if (state.programDepth > 0) {
      state.programDepth = 0;
      history.back();
    } else {
      history.replaceState(null, '', '#' + (state.bgView || 'explore'));
      route();
    }
  } else {
    state.programDepth = 0;
  }
  requestAnimationFrame(() => {
    const scope = origin && origin.scope ? document.getElementById(origin.scope) : document;
    const back = origin && origin.id ? byData('data-detail', origin.id, scope || document) : null;
    const target = back && back.isConnected ? back : $('#explore-view').hidden ? null : $('#explorer-title');
    if (target) target.focus({ preventScroll: true });
  });
}

// ---------------------------------------------------------------- saving and small messages
function toast(message) {
  clearTimeout(toastTimer);
  $('#toast').textContent = message;
  $('#toast').classList.add('visible');
  toastTimer = setTimeout(() => $('#toast').classList.remove('visible'), 2600);
}

function toggleSave(id) {
  const was = isSaved(id);
  state.saved = was ? state.saved.filter((v) => v !== id) : [...state.saved, id];
  let persisted = true;
  try { localStorage.setItem(SAVED_KEY, JSON.stringify(state.saved)); } catch { persisted = false; }
  const scope = document.activeElement && document.activeElement.closest('#home-view, #explore-view');
  renderHome();
  renderResults();
  renderSavedCount();
  if (scope) {
    const target = byData('data-save', id, scope) || scope.querySelector('[data-save]') || $('#reset-results');
    if (target && !target.hidden) target.focus({ preventScroll: true });
  }
  const row = state.detailRow;
  $$('#detail-dialog [data-save]').forEach((button) => {
    if (button.getAttribute('data-save') !== id || !row) return;
    button.innerHTML = icon('bookmark') + (was ? 'Save' : 'Saved');
    button.setAttribute('aria-pressed', String(!was));
    button.setAttribute('aria-label', `${was ? 'Save' : 'Remove'} ${row.title} ${was ? 'to' : 'from'} My saved`);
  });
  toast(was ? 'Removed from My saved.' : persisted ? 'Saved on this device.' : 'Saved for this visit. Device storage is unavailable.');
}

// ---------------------------------------------------------------- the questions (every one optional; "not sure" is unknown, never "no")
const QUIZ_STEPS = 4;
const STATUS_FIELDS = [
  ['first_nations', 'fnRegistered', 'Are you registered under the Indian Act?'],
  ['metis', 'metisCitizen', 'Are you a citizen of a Métis government?'],
  ['inuit', 'inuitBeneficiary', 'Are you a beneficiary of an Inuit land-claims agreement?'],
];
let quiz = null; // { step, draft, touched, busy }

const quizOption = (key, value, label, selected) => `<button class="quiz-option ${selected ? 'selected' : ''}" data-quiz-choice="${esc(key)}:${esc(value)}" data-focus-key="${esc(key)}:${esc(value)}" aria-pressed="${selected}">${esc(label)}<span class="option-circle">${icon('check')}</span></button>`;
const quizPill = (field, value, label, selected) => `<button class="quiz-pill ${selected ? 'selected' : ''}" data-quiz-field="${field}:${value}" data-focus-key="${field}:${value}" aria-pressed="${selected}">${esc(label)}</button>`;
const quizSelect = (id, key, label, options, value) => `<div class="quiz-field"><label for="${id}">${label} <span>Optional</span></label><select id="${id}" class="quiz-select" data-quiz-select="${key}">${options.map(([v, l]) => `<option value="${esc(v)}"${v === value ? ' selected' : ''}>${esc(l)}</option>`).join('')}</select></div>`;

function quizBody() {
  const d = quiz.draft;
  if (quiz.step === 0) {
    const picked = new Set(d.identity);
    const none = picked.size === 0 && quiz.touched.has('community');
    return {
      title: 'Your community?', text: 'Choose all that apply, or skip.', ready: picked.size > 0 || quiz.touched.has('community'),
      html: `<div class="quiz-options" role="group" aria-labelledby="quiz-title">${M.IDENTITIES.map(([v, l]) => quizOption('identity', v, l, picked.has(v))).join('')}${quizOption('identity', 'none', 'Prefer not to say', none)}</div>`,
    };
  }
  if (quiz.step === 1) {
    const w = M.whereOf(d, state.institutions);
    const bc = state.institutions.filter((i) => i.province === 'BC').map((i) => [i.id, i.name]);
    const away = M.PROVINCES.filter(([code]) => code !== 'BC');
    const extra = w.where === 'bc' && bc.length ? quizSelect('quiz-school', 'school', 'Which school?', [['', 'I’m not sure yet'], ...bc], w.school)
      : w.where === 'elsewhere' ? quizSelect('quiz-province', 'studyProvince', 'Which province or territory?', [['', 'I’m not sure yet'], ...away], w.province) : '';
    return {
      title: 'Where will you study?', text: 'Some funding is only for students at one school.', ready: w.where !== '',
      html: `<div class="quiz-options" role="group" aria-labelledby="quiz-title">${quizOption('where', 'bc', 'British Columbia', w.where === 'bc')}${quizOption('where', 'elsewhere', 'Elsewhere in Canada', w.where === 'elsewhere')}${quizOption('where', 'unsure', 'Not sure yet', w.where === 'unsure')}</div>${extra}`,
    };
  }
  if (quiz.step === 2) {
    const levels = d.goal === 'postsecondary'
      ? `<p class="quiz-subtitle">Which level? <span>Optional</span></p><div class="quiz-options is-compact" role="group" aria-label="Level of study">${M.POSTSECONDARY_LEVELS.map(([v, l]) => quizOption('level', v, l, d.level === v)).join('')}</div>` : '';
    return {
      title: 'What’s your next step?', text: 'Choose the direction that fits your plans.', ready: Boolean(d.goal),
      html: `<div class="quiz-options" role="group" aria-labelledby="quiz-title">${M.GOALS.map(([v, l]) => quizOption('goal', v, l, d.goal === v)).join('')}</div>${levels}`,
    };
  }
  const groups = STATUS_FIELDS.filter(([id]) => d.identity.includes(id));
  const yesNo = (field) => [['yes', 'Yes'], ['no', 'No']].map(([v, l]) => quizPill(field, v, l, d[field] === v)).join('');
  return {
    title: 'A few more details?', text: 'Some funding depends on these. Every question is optional.', ready: true,
    html: `<div class="quiz-group"><p class="quiz-group-title" id="q-status">Full-time or part-time?</p><div class="quiz-pills" role="group" aria-labelledby="q-status">${quizPill('studyStatus', 'full_time', 'Full-time', d.studyStatus === 'full_time')}${quizPill('studyStatus', 'part_time', 'Part-time', d.studyStatus === 'part_time')}</div></div>${quizSelect('quiz-residence', 'residence', 'Where do you live right now?', [['', 'Choose a province or territory'], ...M.PROVINCES], d.province)}${groups.map(([, field, question]) => `<div class="quiz-group"><p class="quiz-group-title" id="q-${field}">${question}</p><div class="quiz-pills" role="group" aria-labelledby="q-${field}">${yesNo(field)}</div></div>`).join('')}`,
  };
}

function renderQuiz(focusKey) {
  const body = quizBody();
  const last = quiz.step === QUIZ_STEPS - 1;
  $('#quiz-progress').innerHTML = Array.from({ length: QUIZ_STEPS }, (_, i) => `<span class="${i <= quiz.step ? 'complete' : ''}"></span>`).join('');
  $('#quiz-content').innerHTML = `<p class="quiz-count">QUESTION ${quiz.step + 1} OF ${QUIZ_STEPS}</p><h2 class="quiz-content-title" id="quiz-title" tabindex="-1">${body.title}</h2><p class="quiz-content-description">${body.text}</p>${body.html}<div class="quiz-bottom">${quiz.step > 0 ? '<button class="quiz-back" data-quiz-back>← Back</button>' : '<span></span>'}<button class="quiz-skip" data-quiz-skip>Skip</button><button class="button" data-quiz-next ${body.ready && !quiz.busy ? '' : 'disabled'}>${quiz.busy ? 'Matching…' : last ? 'See matches' : 'Next'} ${icon('arrow')}</button></div><p class="quiz-privacy">${icon('shield')}Optional. Used once to sort the list, never saved.</p>`;
  if (focusKey) { const el = byData('data-focus-key', focusKey, $('#quiz-content')); if (el) el.focus(); }
}

function startQuiz() {
  if (state.phase !== 'ready') { toast(state.phase === 'loading' ? 'The funding list is still loading. Try again in a moment.' : 'The funding list could not be loaded.'); return; }
  quiz = { step: 0, draft: M.cloneAnswers(state.answers), touched: new Set(state.answers.identity.length ? ['community'] : []), busy: false };
  renderQuiz();
  const dialog = $('#quiz-dialog');
  if (!dialog.open) dialog.showModal();
}

function splitKey(raw) {
  const at = raw.indexOf(':');
  return [raw.slice(0, at), raw.slice(at + 1)];
}

function quizChoose(raw) {
  const [key, value] = splitKey(raw);
  const d = M.cloneAnswers(quiz.draft);
  if (key === 'identity') {
    if (value === 'none') {
      d.identity = [];
      quiz.touched.add('community');
    } else {
      const set = new Set(d.identity);
      if (set.has(value)) set.delete(value); else set.add(value);
      d.identity = M.IDENTITIES.map(([k]) => k).filter((k) => set.has(k));
    }
    quiz.draft = d;
  } else if (key === 'where') {
    const w = M.whereOf(d, state.institutions);
    quiz.draft = M.withWhere(d, { where: value, school: value === w.where ? w.school : '', province: value === w.where ? w.province : '' });
  } else if (key === 'goal') {
    quiz.draft = M.withGoal(d, value, value === d.goal ? d.level : '');
  } else if (key === 'level') {
    quiz.draft = M.withGoal(d, 'postsecondary', d.level === value ? '' : value);
  }
  renderQuiz(raw);
}

function quizPillChoose(raw) {
  const [field, value] = splitKey(raw);
  if (!['studyStatus', 'fnRegistered', 'metisCitizen', 'inuitBeneficiary'].includes(field)) return;
  const d = M.cloneAnswers(quiz.draft);
  d[field] = d[field] === value ? '' : value;
  quiz.draft = d;
  renderQuiz(raw);
}

function quizSelectChanged(key, value) {
  const d = M.cloneAnswers(quiz.draft);
  if (key === 'school') quiz.draft = M.withWhere(d, { where: 'bc', school: value });
  else if (key === 'studyProvince') quiz.draft = M.withWhere(d, { where: 'elsewhere', province: value });
  else if (key === 'residence') quiz.draft = { ...d, province: value };
}

function quizAdvance() {
  if (quiz.step === QUIZ_STEPS - 1) { finishQuiz(); return; }
  quiz.step += 1;
  renderQuiz();
  $('#quiz-title').focus();
}

function quizSkip() {
  let d = M.cloneAnswers(quiz.draft);
  if (quiz.step === 0) { d.identity = []; quiz.touched.add('community'); }
  else if (quiz.step === 1) d = M.withWhere(d, { where: '' });
  else if (quiz.step === 2) d = M.withGoal(d, '');
  else d = { ...d, province: '', studyStatus: '', fnRegistered: '', metisCitizen: '', inuitBeneficiary: '' };
  quiz.draft = d;
  quizAdvance();
}

async function finishQuiz() {
  quiz.busy = true;
  renderQuiz();
  const ok = await applyAnswers(quiz.draft);
  if (!quiz) return;
  quiz.busy = false;
  if (!ok) { renderQuiz(); return; }
  $('#quiz-dialog').close();
  go('explore');
  toast(state.personalized ? 'Your preferences are applied.' : 'No preferences were set.');
}

// ---------------------------------------------------------------- information dialogs
function infoContent(key) {
  const mail = CONFIG.contactEmail ? esc(CONFIG.contactEmail) : '';
  const demo = state.mode === 'demo' ? '<p><strong>This server is in demo mode.</strong> The scholarships you see are made up for testing.</p>' : '';
  const pages = {
    privacy: {
      title: 'Your information stays yours.',
      body: `<p><strong>No name, status number or documents.</strong> Your answers are sent to the Funding Navigator service once, to sort the list. The service does not save them or write them to a log, and this page keeps them in memory only: reloading clears them.</p><p>My saved keeps only the ids of the opportunities you save, on this device. It does not store your answers. Apply directly with the provider and review their privacy policy before sharing documents.</p><button class="text-link" data-clear-saved>Clear My saved on this device ${icon('arrow')}</button>`,
    },
    sources: {
      title: 'Where this information comes from.',
      body: `${demo}<p><strong>Checked on the provider’s page:</strong> a computer read the provider’s own web page, and every detail we show is backed by a quote from it. Open a program and choose “Source & current details” to read the quotes.</p><p><strong>Government directory entry:</strong> listed in a federal directory of Indigenous bursaries. These entries can be many years old and have no deadline, so treat them as a lead and confirm with the provider.</p><p>“Checked” means a computer verified the quotes; a person has not reviewed it yet. Matches compare your answers with what the provider published. They never predict whether you will receive funding.</p><p>Information from Indigenous Services Canada (the Indigenous Bursaries Search Tool and its program pages) is reproduced under the Government of Canada’s non-commercial reproduction terms. These copies are not official versions, and this site was not produced in affiliation with, or with the endorsement of, the Government of Canada.</p><p>Some websites refuse automated access, for example parts of UBC’s. We do not work around that, so those awards are missing until the provider agrees.</p><p>The same information is open data: <a href="/opportunities">the list</a> and <a href="/docs">the API documentation</a>.${mail ? ` Run a program shown here, or found something out of date? <a href="mailto:${mail}">${mail}</a>.` : ''}</p>`,
    },
    about: {
      title: 'A little support.<br>A world of possibility.',
      body: '<p>Funding Navigator is a free, non-commercial guide to scholarships, bursaries and funding programs for First Nations, Inuit and Métis students in Canada. It does not take applications and it does not choose winners.</p><p>It compares your answers with the conditions each provider has published. A card can say that you meet what we can check, that something needs the provider’s confirmation, or that you probably do not qualify. It never estimates your chances of receiving funding.</p>',
    },
    help: {
      title: 'A helping hand.',
      body: '<p>Bring an opportunity link to your <strong>school financial aid advisor, Indigenous student centre or community education office</strong>. Ask which documents and dates you need to confirm.</p><p>For PSSSP, contact your First Nation or designated organization. For Inuit support, contact your regional Inuit organization. For MNBC support, contact STEPS.</p>',
    },
  };
  return pages[key] || pages.about;
}

function openInfo(key) {
  const info = infoContent(key);
  $('#info-content').innerHTML = `<h2 id="info-title">${info.title}</h2>${info.body}`;
  $('#info-dialog').showModal();
}

// ---------------------------------------------------------------- filters, chips, clearing
function refresh() {
  renderFilters();
  renderResults();
}

function clearFilters() {
  state.query = '';
  state.type = 'all';
  state.amount = 'any';
  state.page = 1;
  $('#funding-search').value = '';
  if (state.personalized) { applyAnswers(M.blankAnswers()); return; }
  state.answers = M.blankAnswers();
  refresh();
  renderProfile();
}

function removeFilter(key) {
  if (key === 'type') { state.type = 'all'; state.page = 1; refresh(); return; }
  if (key === 'amount') { state.amount = 'any'; state.page = 1; refresh(); return; }
  if (key === 'community') { applyAnswers(M.withCommunity(state.answers, '')); return; }
  if (key === 'location') { applyAnswers(M.withLocation(state.answers, '')); return; }
  removeAnswer(key);
}

function removeAnswer(key) {
  const a = M.cloneAnswers(state.answers);
  if (key === 'province') a.province = '';
  else if (key === 'level') { a.level = ''; a.goal = ''; }
  else if (key === 'studyStatus') a.studyStatus = '';
  applyAnswers(a);
}

// ---------------------------------------------------------------- routes: #home, #explore, #saved, #profile, #program/<id>
const WORKSPACE = ['explore', 'saved', 'profile'];

function go(view) {
  if (location.hash !== '#' + view) location.hash = view;
  route();
}

function route() {
  const r = M.parseRoute(location.hash);
  const program = r.view === 'program';
  const view = program ? (state.bgView || 'explore') : r.view;
  const workspace = WORKSPACE.includes(view);
  const profile = view === 'profile';
  const current = workspace ? view : 'home';
  if (!program) state.bgView = current;
  state.savedOnly = view === 'saved';
  $('#workspace-location').textContent = profile ? 'My profile' : state.savedOnly ? 'My saved' : 'Explore funding';
  $('#home-view').hidden = workspace;
  $('#workspace-view').hidden = !workspace;
  $('#explore-view').hidden = !workspace || profile;
  $('#profile-view').hidden = !profile;
  document.body.classList.toggle('workspace-mode', workspace);
  $$('[data-nav]').forEach((link) => { if (workspace && link.dataset.nav === view) link.setAttribute('aria-current', 'page'); else link.removeAttribute('aria-current'); });
  if (profile) renderProfile();
  else if (workspace) refresh();
  if (!program) {
    document.title = workspace ? `${profile ? 'My profile' : view === 'saved' ? 'My saved' : 'Explore funding'} — Funding Navigator` : 'Funding Navigator — Find your next chapter';
    if (view === 'how-it-works') {
      requestAnimationFrame(() => $('#how-it-works').scrollIntoView({ behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth' }));
    } else if (previousView !== current) {
      window.scrollTo({ top: 0, behavior: 'instant' });
      if (previousView) (profile ? $('#profile-title') : workspace ? $('#explorer-title') : $('#hero-title')).focus({ preventScroll: true });
    }
    previousView = current;
  }
  if (program) showProgram(r.id);
  else if ($('#detail-dialog').open) $('#detail-dialog').close();
}

// ---------------------------------------------------------------- events
document.addEventListener('click', (event) => {
  const t = event.target;
  const close = t.closest('[data-close]');
  if (close) { close.closest('dialog').close(); return; }
  const save = t.closest('[data-save]');
  if (save) { toggleSave(save.getAttribute('data-save')); return; }
  const detail = t.closest('[data-detail]');
  if (detail) {
    const id = detail.getAttribute('data-detail');
    if (!$('#detail-dialog').open) rememberOrigin(id);
    openProgram(id);
    return;
  }
  if (t.closest('[data-quiz]')) { startQuiz(); return; }
  const info = t.closest('[data-info]');
  if (info) { openInfo(info.dataset.info); return; }
  const preview = t.closest('[data-preview-filter]');
  if (preview) { go('explore'); requestAnimationFrame(() => $(`#quick-${preview.dataset.previewFilter}`).focus()); return; }
  const tab = t.closest('[data-program-tab]');
  if (tab) { setProgramTab(tab.dataset.programTab); return; }
  const layout = t.closest('[data-layout]');
  if (layout) { state.layout = layout.dataset.layout; refresh(); return; }
  const removal = t.closest('[data-remove-filter]');
  if (removal) { removeFilter(removal.dataset.removeFilter); return; }
  const move = t.closest('[data-program-move]');
  if (move) { moveProgram(Number(move.dataset.programMove)); return; }
  if (t.closest('[data-clear-filters]')) { clearFilters(); return; }
  if (t.closest('[data-toggle-no]')) { state.showNo = !state.showNo; state.page = 1; renderResults(); return; }
  if (t.closest('[data-show-more]')) { state.page += 1; renderResults(); return; }
  if (t.closest('[data-retry]')) { state.loading = loadData(); return; }
  const choice = t.closest('[data-quiz-choice]');
  if (choice && quiz) { quizChoose(choice.getAttribute('data-quiz-choice')); return; }
  const pill = t.closest('[data-quiz-field]');
  if (pill && quiz) { quizPillChoose(pill.getAttribute('data-quiz-field')); return; }
  if (t.closest('[data-quiz-next]') && quiz) { quizAdvance(); return; }
  if (t.closest('[data-quiz-skip]') && quiz) { quizSkip(); return; }
  if (t.closest('[data-quiz-back]') && quiz) { quiz.step = Math.max(0, quiz.step - 1); renderQuiz(); $('#quiz-title').focus(); return; }
  if (t.closest('[data-use-profile]')) { go('explore'); return; }
  if (t.closest('[data-clear-profile]')) { applyAnswers(M.blankAnswers()).then((ok) => { if (ok) toast('Preferences cleared.'); }); return; }
  if (t.closest('[data-clear-saved]')) {
    state.saved = [];
    try { localStorage.removeItem(SAVED_KEY); } catch { /* nothing was stored */ }
    renderSavedCount(); renderHome(); renderResults();
    $('#info-dialog').close();
    toast('My saved has been cleared.');
  }
});

document.addEventListener('keydown', (event) => {
  const tab = event.target.closest('[data-program-tab]');
  if (!tab) return;
  const values = ['overview', 'eligibility', 'steps'];
  let index = values.indexOf(tab.dataset.programTab);
  if (event.key === 'ArrowRight') index = (index + 1) % values.length;
  else if (event.key === 'ArrowLeft') index = (index + values.length - 1) % values.length;
  else if (event.key === 'Home') index = 0;
  else if (event.key === 'End') index = values.length - 1;
  else return;
  event.preventDefault();
  setProgramTab(values[index], true);
});

document.addEventListener('change', (event) => {
  const select = event.target.closest('[data-quiz-select]');
  if (select && quiz) quizSelectChanged(select.dataset.quizSelect, select.value);
});

$('#quick-community').addEventListener('change', (event) => { applyAnswers(M.withCommunity(state.answers, event.target.value)); });
$('#quick-location').addEventListener('change', (event) => { applyAnswers(M.withLocation(state.answers, event.target.value)); });
$('#quick-type').addEventListener('change', (event) => { state.type = event.target.value; state.page = 1; refresh(); });
$('#quick-amount').addEventListener('change', (event) => { state.amount = event.target.value; state.page = 1; refresh(); });
$('#funding-sort').addEventListener('change', (event) => { state.sort = event.target.value; state.page = 1; renderResults(); });
$('#funding-search').addEventListener('input', (event) => { state.query = event.target.value; state.page = 1; refresh(); });
$('#search-form').addEventListener('submit', (event) => { event.preventDefault(); state.query = $('#funding-search').value; state.page = 1; refresh(); });
$('#reset-results').addEventListener('click', () => {
  if (state.savedOnly && state.saved.length === 0) { go('explore'); return; }
  clearFilters();
});

$$('dialog').forEach((dialog) => dialog.addEventListener('click', (event) => {
  if (event.target !== dialog) return;
  const rect = dialog.getBoundingClientRect();
  if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) dialog.close();
}));
$('#detail-dialog').addEventListener('close', onDetailClosed);
$('#quiz-dialog').addEventListener('close', () => { quiz = null; });

window.addEventListener('hashchange', route);

// ---------------------------------------------------------------- start
loadSaved();
state.loading = loadData();
route();
