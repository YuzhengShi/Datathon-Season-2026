// The results page: the part that works like a store. Search on top, filters on the left, sort, and one card per scholarship.
import { h, icon } from './dom.js';
import { AMOUNT_BUCKETS, SORTS, applyFilters, cap, cardSummary, prettyRule, defaultFilters, describeAnswers, detailHash, facetCounts, sortRows } from './logic.js';
import { availabilityBadge, banner, deadlineBlock, fitBadge, priceBlock, saveButton, sourceBadge, thumb } from './views_common.js';

const plural = (n, word) => `${n} ${word}${n === 1 ? '' : 's'}`;

function cardFacts(row, personalized, institutions) {
  const out = [];
  if (personalized) {
    const c = row.counts;
    if (c.passed) out.push(h('li', { class: 'ok' }, icon('check', 15), `You meet ${plural(c.passed, 'requirement')} we can check`));
    if (c.confirm) out.push(h('li', { class: 'ask' }, icon('help', 15), `${c.confirm} to confirm with the provider`));
    if (c.needAnswer) out.push(h('li', { class: 'ask' }, icon('help', 15), `${plural(c.needAnswer, 'more answer')} would help`));
    if (c.failed && row.failed[0]) out.push(h('li', {}, icon('x', 15), cap(prettyRule(row.failed[0], institutions))));
  }
  return out;
}

function card(row, ctx) {
  const personalized = ctx.state.personalized;
  const href = detailHash(row.id);
  return h('li', { class: row.fit.key === 'no' && personalized ? 'card card--muted' : 'card' },
    thumb(row.category),
    h('div', { class: 'card__body' },
      h('h2', { class: 'card__title' }, h('a', { href }, row.title)),
      h('p', { class: 'card__provider' }, row.provider, row.donor ? ` · funded by ${row.donor}` : ''),
      h('div', { class: 'badges' }, personalized ? fitBadge(row) : null, sourceBadge(row), availabilityBadge(row)),
      h('p', { class: 'card__summary' }, cardSummary(row)),
      h('ul', { class: 'facts' }, cardFacts(row, personalized, ctx.state.institutions))),
    h('div', { class: 'card__aside' },
      priceBlock(row), deadlineBlock(row),
      h('div', { class: 'card__actions' }, h('a', { class: 'btn btn--primary btn--small', href }, 'View details'), saveButton(row, ctx))));
}

const FACETS = [
  { key: 'fit', title: 'Fit for you', personalOnly: true, options: [['fit', 'Looks like a fit'], ['meets', 'Meets what we can check'], ['ask', 'Ask the provider about eligibility'], ['more', 'More answers would help']] },
  { key: 'type', title: 'Type', options: [['award', 'Scholarships, awards and bursaries'], ['funding_channel', 'Funding programs']] },
  { key: 'source', title: 'Where we found it', options: [['official_page', 'The provider’s own page'], ['directory_listing', 'Government directory (may be out of date)']] },
  { key: 'avail', title: 'Timing', options: [['open', 'Open now'], ['upcoming', 'Opens soon'], ['contact_administrator', 'Ask the administrator'], ['unknown', 'Dates not confirmed']] },
];

function facetPanels(ctx, counts, update, suffix) {
  const st = ctx.state;
  const panels = [];
  for (const facet of FACETS) {
    if (facet.personalOnly && !st.personalized) continue;
    const chosen = st.filters[facet.key];
    const options = facet.options.filter(([value]) => (counts[facet.key][value] || 0) > 0 || chosen.has(value));
    if (!options.length) continue;
    panels.push(h('fieldset', { class: 'facet' }, h('legend', {}, facet.title), options.map(([value, label]) =>
      h('label', { class: 'check' },
        h('input', { type: 'checkbox', checked: chosen.has(value), onChange: (e) => { if (e.target.checked) chosen.add(value); else chosen.delete(value); update(); } }),
        h('span', {}, label), h('span', { class: 'check__n' }, String(counts[facet.key][value] || 0))))));
  }
  panels.push(h('fieldset', { class: 'facet' }, h('legend', {}, 'Amount'), AMOUNT_BUCKETS.map(([value, label]) =>
    h('label', { class: 'check' },
      h('input', { type: 'radio', name: `amount-${suffix}`, checked: st.filters.amount === value, onChange: () => { st.filters.amount = value; update(); } }),
      h('span', {}, label)))));
  if (st.personalized) {
    const hidden = st.rows.filter((r) => r.fit.key === 'no').length;
    if (hidden) {
      panels.push(h('div', { class: 'facet' }, h('label', { class: 'check' },
        h('input', { type: 'checkbox', checked: st.filters.showNo, onChange: (e) => { st.filters.showNo = e.target.checked; update(); } }),
        h('span', {}, 'Also show ones I probably do not qualify for'), h('span', { class: 'check__n' }, String(hidden)))));
    }
  }
  return panels;
}

function activeChips(ctx, update) {
  const f = ctx.state.filters;
  const labels = new Map(FACETS.flatMap((facet) => facet.options.map(([value, label]) => [`${facet.key}:${value}`, label])));
  const chips = [];
  const chip = (text, remove) => chips.push(h('span', { class: 'chip chip--filter' }, text,
    h('button', { type: 'button', 'aria-label': `Remove filter: ${text}`, onClick: () => { remove(); update(); } }, icon('x', 14))));
  if (f.q.trim()) chip(`Search: “${f.q.trim()}”`, () => { f.q = ''; const box = document.querySelector('.search__input'); if (box) box.value = ''; });
  for (const facet of FACETS) for (const value of f[facet.key]) chip(labels.get(`${facet.key}:${value}`), () => f[facet.key].delete(value));
  if (f.amount !== 'any') chip((AMOUNT_BUCKETS.find(([v]) => v === f.amount) || [])[1], () => { f.amount = 'any'; });
  return chips;
}

function answersBar(ctx) {
  const st = ctx.state;
  const inner = [];
  if (st.mode === 'sample') {
    inner.push(h('span', { class: 'chip' }, 'Example answers'), ...describeAnswers(st.answers, st.institutions).map((t) => h('span', { class: 'chip chip--filter' }, t)),
      h('a', { class: 'btn btn--secondary btn--small', href: '#/start/1' }, 'Use my own answers'));
  } else if (st.personalized) {
    inner.push(h('span', { class: 'muted small' }, 'Showing funding for:'), ...describeAnswers(st.answers, st.institutions).map((t) => h('span', { class: 'chip' }, t)),
      h('a', { href: '#/start/1' }, 'Edit my answers'));
  } else {
    inner.push(icon('info', 18), h('span', {}, st.mode === 'browse' ? 'You are browsing everything. ' : 'You skipped the questions, so nothing is judged yet. '),
      h('a', { class: 'btn btn--secondary btn--small', href: '#/start/1' }, 'Answer a few questions to see how you match'));
  }
  return h('div', { class: 'answers-bar' }, h('div', { class: 'container answers-bar__inner' }, ...inner));
}

export function resultsView(ctx) {
  const st = ctx.state;
  const filtersBox = h('aside', { class: 'filters', 'aria-label': 'Filters' });
  const sheetBody = h('div', { class: 'dialog__body sheet' });
  const showBtn = h('button', { class: 'btn btn--primary', type: 'button' }, 'Show results');
  const sheet = h('dialog', { 'aria-label': 'Filters' },
    h('div', { class: 'dialog__head' }, h('h2', {}, 'Filters'), h('button', { class: 'btn btn--ghost btn--small', type: 'button', 'aria-label': 'Close filters', onClick: () => sheet.close() }, icon('x', 18))),
    sheetBody, h('div', { class: 'dialog__foot' }, showBtn, h('button', { class: 'btn btn--secondary', type: 'button', onClick: () => { Object.assign(st.filters, defaultFilters()); update(); } }, 'Clear all')));
  showBtn.addEventListener('click', () => sheet.close());
  const countEl = h('h1', { class: 'results__count', id: 'page-title', tabindex: '-1' });
  const chipsBox = h('div', { class: 'badges' });
  const listBox = h('div', {});
  const sort = h('select', { class: 'select', id: 'sort', onChange: (e) => { st.sort = e.target.value; update(); } }, SORTS.map(([value, label]) => h('option', { value, selected: st.sort === value }, label)));
  const head = h('div', { class: 'results__head' }, countEl, h('div', { class: 'results__tools' },
    h('button', { class: 'btn btn--secondary btn--small only-mobile', type: 'button', onClick: () => sheet.showModal() }, icon('sliders', 16), 'Filters'),
    h('label', { class: 'sort', for: 'sort' }, h('span', { class: 'sort__label' }, 'Sort by'), sort)));
  const notices = [];
  if (st.excludedClosed) notices.push(banner('info', 'clock', h('p', {}, `${plural(st.excludedClosed, 'program')} closed to applications ${st.excludedClosed === 1 ? 'is' : 'are'} hidden.`)));
  const node = h('div', {}, answersBar(ctx), h('div', { class: 'container' }, h('div', { class: 'layout' }, filtersBox,
    h('section', { class: 'results', 'aria-label': 'Results' }, ...notices, head, chipsBox, listBox))), sheet);

  function update() {
    const personalized = st.personalized;
    const counts = facetCounts(st.rows, st.filters, personalized);
    const shown = sortRows(applyFilters(st.rows, st.filters, personalized), st.sort, personalized);
    filtersBox.replaceChildren(h('h2', { class: 'facet__title' }, 'Narrow your results'), ...facetPanels(ctx, counts, update, 'side'),
      h('button', { class: 'link-button', type: 'button', onClick: () => { Object.assign(st.filters, defaultFilters()); const box = document.querySelector('.search__input'); if (box) box.value = ''; update(); } }, 'Clear all filters'));
    sheetBody.replaceChildren(...facetPanels(ctx, counts, update, 'sheet'));
    showBtn.textContent = `Show ${plural(shown.length, 'result')}`;
    countEl.textContent = plural(shown.length, 'result');
    chipsBox.replaceChildren(...activeChips(ctx, update));
    listBox.replaceChildren(shown.length
      ? h('ul', { class: 'list' }, shown.map((row) => card(row, ctx)))
      : h('div', { class: 'empty' }, h('h2', {}, 'Nothing matches these filters'), h('p', { class: 'muted' }, 'Try removing a filter or clearing the search.'),
        h('button', { class: 'btn btn--primary', type: 'button', onClick: () => { Object.assign(st.filters, defaultFilters()); update(); } }, 'Clear all filters')));
    ctx.announce(`${plural(shown.length, 'result')}`);
  }
  update();
  return { node, update };
}
