// The detail page: everything about one scholarship, what is checked, what is not, and exactly where each fact was read.
import { h, icon } from './dom.js';
import { cap, cardSummary, detailHash, evidenceList, flagText, plainDate, prettyRule, providerStatements, sourceView } from './logic.js';
import { availabilityBadge, banner, deadlineBlock, fitBadge, priceBlock, saveButton, sourceBadge } from './views_common.js';

const MARKS = { pass: 'check', fail: 'x', unknown: 'help' };
const ruleItem = (kind, text, why) => h('li', { class: `rule rule--${kind}` },
  h('span', { class: 'rule__mark' }, icon(MARKS[kind], 15)), h('span', {}, cap(text), why ? h('span', { class: 'rule__why' }, why) : null));
const panel = (title, iconName, ...body) => h('section', { class: 'panel' }, h('h2', {}, icon(iconName, 20), title), ...body);

function aboutPanel(row, detail) {
  const statements = providerStatements(detail);
  const lead = row.source_kind === 'directory_listing' ? cardSummary(row) : row.summary;
  return panel('About this funding', 'info',
    lead ? h('p', {}, lead) : null,
    statements.length ? [h('h3', {}, 'In the provider’s words'), h('ul', {}, statements.map((s) => h('li', {}, s)))] : null);
}

function matchPanel(row, ctx, detail) {
  if (!ctx.state.personalized) {
    const schools = ctx.state.institutions;
    // the provider's own sentences are already shown above: do not list them a second time as requirements
    const said = new Set(providerStatements(detail).map((s) => s.replace(/\s+/g, ' ').trim().toLowerCase()));
    const listed = [...row.passed, ...row.failed, ...row.unknown].filter((r) => !said.has(String(r.rule).replace(/\s+/g, ' ').trim().toLowerCase()));
    return panel('What the provider asks for', 'list',
      listed.length ? h('ul', { class: 'checklist' }, listed.map((r) => h('li', {}, cap(prettyRule(r, schools))))) : h('p', { class: 'muted' }, 'The provider does not list requirements we can read automatically.'),
      h('p', {}, h('a', { class: 'btn btn--secondary btn--small', href: '#/start/1' }, 'Answer a few questions to see how you match')));
  }
  const schools = ctx.state.institutions;
  const items = [
    ...row.passed.map((r) => ruleItem('pass', prettyRule(r, schools), 'This matches your answers.')),
    ...row.failed.map((r) => ruleItem('fail', prettyRule(r, schools), 'This does not match your answers.')),
    ...row.unknown.map((r) => ruleItem('unknown', prettyRule(r, schools), r.unknown_reason === 'profile_missing' ? 'We need an answer from you to check this.' : 'Only the provider can confirm this.')),
  ];
  return panel('How you match', 'check',
    h('p', {}, h('strong', {}, row.fit.label + '. '), 'This compares your answers with what the provider has published. It is not a prediction of whether you would receive the funding.'),
    items.length ? h('ul', { class: 'checklist' }, items) : h('p', { class: 'muted' }, 'The provider has not published conditions we can check. Ask them who is eligible.'),
    row.questions.length ? [h('h3', {}, 'Answer these to improve the match'), h('ul', {}, row.questions.map((q) => h('li', {}, q))), h('p', {}, h('a', { href: '#/start/1' }, 'Edit my answers'))] : null);
}

function sourcePanel(row, detail) {
  const s = sourceView(row);
  const quotes = evidenceList(row, detail);
  return panel('Where this information comes from', 'shield',
    h('div', { class: `source-note source-note--${s.tone === 'warn' ? 'warn' : 'good'}` }, icon(s.tone === 'warn' ? 'info' : 'shield', 20), h('p', {}, h('strong', {}, s.label + '. '), s.note)),
    quotes.length ? [h('h3', {}, 'What the page says'), quotes.slice(0, 8).map((q) => h('blockquote', { class: 'quote' },
      h('p', {}, '“' + q.quote + '”'),
      h('footer', {}, q.label, q.heading ? ` · under “${q.heading}”` : '', q.url ? [' · ', h('a', { href: q.url, target: '_blank', rel: 'noopener noreferrer' }, 'open the page')] : null)))] : null,
    h('p', { class: 'small muted' }, 'A computer read this page and checked that every quote above appears on it. A person has not reviewed it yet, so always confirm on the provider’s page.',
      row.lastVerified ? ` Last checked ${plainDate(row.lastVerified)}.` : ''));
}

function sharedPanel(detail) {
  const siblings = (detail && detail.shared_application_with) || [];
  if (!siblings.length) return null;
  const shown = siblings.slice(0, 12);
  return panel('One application covers several awards', 'list',
    h('p', {}, `The provider uses the same application for ${siblings.length} other award${siblings.length === 1 ? '' : 's'}. Apply once; each award still has its own conditions, so read them.`),
    h('ul', {}, shown.map((s) => h('li', {}, h('a', { href: detailHash(s.id) }, s.title)))),
    siblings.length > shown.length ? h('p', { class: 'small muted' }, `and ${siblings.length - shown.length} more`) : null);
}

function goodToKnow(row) {
  const notes = [...row.funderConditions.map((c) => c.text || c.rule || ''), ...row.flags.map(flagText)].filter(Boolean);
  if (!notes.length && !row.nextAction) return null;
  return panel('Good to know', 'info', notes.length ? h('ul', {}, [...new Set(notes)].map((n) => h('li', {}, n))) : null,
    row.nextAction ? h('p', {}, row.nextAction.replace(/ Contact them via https?:\/\/\S+\.?$/, '')) : null);
}

function sameTarget(a, b) {
  try {
    const x = new URL(a, location.href);
    const y = new URL(b, location.href);
    return x.origin + x.pathname === y.origin + y.pathname;
  } catch {
    return a === b;
  }
}

function buyBox(row, ctx) {
  const route = row.route || {};
  const applyUrl = route.url || row.officialUrl;
  const label = route.route_type === 'contact_administrator' ? 'See how to apply' : route.route_type === 'online_application' ? 'Go to the application' : 'Go to the provider’s page';
  const external = { target: '_blank', rel: 'noopener noreferrer' };
  return h('aside', { class: 'buybox', 'aria-label': 'Apply' },
    priceBlock(row),
    h('dl', { class: 'kv' },
      h('dt', {}, 'Deadline'), h('dd', {}, deadlineBlock(row)),
      h('dt', {}, 'Provider'), h('dd', {}, row.provider)),
    h('div', { class: 'badges' }, availabilityBadge(row)),
    h('a', { class: 'btn btn--primary btn--block', href: applyUrl, ...external }, label, icon('external', 16)),
    !sameTarget(applyUrl, row.officialUrl) ? h('p', {}, h('a', { class: 'btn btn--secondary btn--block btn--small', href: row.officialUrl, ...external }, 'Read the provider’s page')) : null,
    h('p', {}, saveButton(row, ctx, { block: true })),
    route.instructions ? h('p', { class: 'small' }, route.instructions) : null,
    route.contact_url ? h('p', { class: 'small' }, h('a', { href: route.contact_url, ...external }, 'Contact the provider')) : null,
    h('p', { class: 'small muted' }, 'You apply directly with the provider. Funding Navigator does not take applications.'));
}

export function detailView(ctx, row, detail) {
  const personalized = ctx.state.personalized;
  return h('div', { class: 'page' }, h('div', { class: 'container' },
    h('p', { class: 'crumbs' }, h('a', { href: ctx.state.mode === 'none' ? '#/' : '#/results' }, icon('back', 16), ctx.state.mode === 'none' ? 'Back to the start' : 'Back to results')),
    h('h1', { id: 'page-title', tabindex: '-1' }, row.title),
    h('p', { class: 'muted' }, row.provider, row.donor ? ` · funded by ${row.donor}` : ''),
    h('div', { class: 'badges' }, personalized ? fitBadge(row) : null, sourceBadge(row), availabilityBadge(row)),
    row.source_kind === 'directory_listing' ? banner('warn', 'info', h('p', {}, h('strong', {}, 'Check the details with the provider. '), 'This comes from a government directory that can be many years old. It lists no deadline.')) : null,
    h('div', { class: 'detail__grid' },
      h('div', {}, aboutPanel(row, detail), matchPanel(row, ctx, detail), sharedPanel(detail), goodToKnow(row), sourcePanel(row, detail)),
      buyBox(row, ctx))));
}
