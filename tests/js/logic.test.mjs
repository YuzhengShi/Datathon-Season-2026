import assert from 'node:assert/strict';
import { test } from 'node:test';

import {
  OTHER_SCHOOL, UNDECIDED_SCHOOL, amountView, applyFilters, buildProfile, buildRow, daysBetween, deadlineView, defaultFilters,
  cardSummary, describeAnswers, evidenceLabel, evidenceList, facetCounts, fitView, flagText, formatMoney, joinRows, nextOccurrence, parseHash, plainDate,
  prettyRule, providerStatements, rowFromDetail, shortlistText, sortRows, sourceView, urgencyText, withDeadlines,
} from '../../frontend/assets/logic.js';
import { governmentAttribution } from '../../frontend/assets/logic.js';

const TODAY = '2026-10-08';
const SCHOOLS = [{ id: 'sfu', name: 'Simon Fraser University', province: 'BC' }];

// ------------------------------------------------------------------ what is sent to the API
test('only answered questions reach the profile; "not sure" is unknown, never "no"', () => {
  const p = buildProfile({ identity: ['first_nations', 'metis'], fnRegistered: 'yes', metisCitizen: '', inuitBeneficiary: 'yes',
    province: 'BC', level: 'undergraduate', studyStatus: 'full_time', school: 'sfu' }, SCHOOLS);
  assert.deepEqual(p, { indigenous_identity: ['first_nations', 'metis'], first_nations_registered: true, residence_province: 'BC',
    education_level: 'undergraduate', study_status: 'full_time', institution_id: 'sfu', institution_province: 'BC' });
  assert.equal('metis_citizen' in p, false);
  assert.equal('inuit_beneficiary' in p, false, 'a follow-up for a group the student did not pick is ignored');
});

test('a skipped questionnaire sends an empty profile; "no" is a real answer', () => {
  assert.deepEqual(buildProfile({}), {});
  assert.equal(buildProfile({ identity: ['first_nations'], fnRegistered: 'no' }).first_nations_registered, false);
});

test('another school sends its name and province; an undecided school sends nothing about the school', () => {
  assert.deepEqual(buildProfile({ school: OTHER_SCHOOL, otherSchoolName: '  Dalhousie University ', otherSchoolProvince: 'NS' }),
    { institution_name: 'Dalhousie University', institution_province: 'NS' });
  assert.deepEqual(buildProfile({ school: UNDECIDED_SCHOOL }), {});
});

test('the answers bar uses plain words', () => {
  const chips = describeAnswers({ identity: ['inuit'], province: 'NU', level: 'undergraduate', studyStatus: 'part_time', school: 'sfu' }, SCHOOLS);
  assert.deepEqual(chips, ['Inuit', 'Lives in Nunavut', 'University', 'Part-time', 'Simon Fraser University']);
});

// ------------------------------------------------------------------ amounts
test('amounts say what the provider lists and nothing more', () => {
  assert.equal(formatMoney('1000'), '$1,000');
  assert.equal(formatMoney('1000.5'), '$1,000.50');
  assert.equal(formatMoney(null), null);
  assert.equal(amountView({ kind: 'fixed', fixed: '4000' }).text, '$4,000');
  assert.equal(amountView({ kind: 'maximum', maximum: '5000' }).text, 'Up to $5,000');
  assert.equal(amountView({ kind: 'range', minimum: '500', maximum: '1000' }).text, '$500–$1,000');
  assert.equal(amountView({ kind: 'pooled_total', pooled_total: '20000' }).text, '$20,000 in total');
  assert.equal(amountView({ kind: 'variable' }).text, 'Varies');
  for (const unclear of [null, {}, { kind: 'unspecified' }, { kind: 'fixed', fixed: 'lots' }]) {
    assert.equal(amountView(unclear).text, 'Amount not listed');
    assert.equal(amountView(unclear).value, null);
  }
});

// ------------------------------------------------------------------ dates
test('plain dates are not shifted by time zones', () => {
  assert.equal(plainDate('2026-11-23'), 'Nov 23, 2026');
  assert.equal(plainDate('2026-11-23T05:00:00Z'), 'Nov 23, 2026');
  assert.equal(plainDate('soon'), null);
  assert.equal(daysBetween('2026-10-08', '2026-11-23'), 46);
  assert.equal(daysBetween('2026-12-30', '2027-01-02'), 3);
});

test('an upcoming date says when, how soon, and that no time zone was given', () => {
  const d = deadlineView([{ kind: 'date', date: '2026-11-23', closing: { state: 'not_closed', flags: ['timezone_unknown'] } }], TODAY);
  assert.deepEqual([d.text, d.days, d.soon, d.closed, d.sortKey], ['Apply by Nov 23, 2026', 46, false, false, '2026-11-23']);
  assert.match(d.detail, /time zone/);
  const soon = deadlineView([{ kind: 'datetime', date: '2026-10-12', local_time: '17:00' }], TODAY);
  assert.deepEqual([soon.text, soon.soon, urgencyText(soon.days)], ['Apply by Oct 12, 2026 at 17:00', true, 'Closes in 4 days']);
  assert.equal(urgencyText(0), 'Closes today');
  assert.equal(urgencyText(1), 'Closes tomorrow');
  assert.equal(urgencyText(-3), null);
});

test('with several dates the next one that has not passed is shown; a past date is "Closed"', () => {
  const d = deadlineView([{ kind: 'date', date: '2026-09-01' }, { kind: 'date', date: '2026-12-01' }], TODAY);
  assert.equal(d.text, 'Apply by Dec 1, 2026');
  const past = deadlineView([{ kind: 'date', date: '2026-09-01' }], TODAY);
  assert.deepEqual([past.text, past.closed, past.days], ['Closed Sep 1, 2026', true, null]);
});

test('repeating deadlines roll over to next year and list every intake', () => {
  const rules = [{ annual_month: 8, annual_day: 1 }, { annual_month: 11, annual_day: 1 }, { annual_month: 2, annual_day: 1 }];
  assert.equal(nextOccurrence(rules, TODAY), '2026-11-01');
  assert.equal(nextOccurrence(rules, '2026-11-02'), '2027-02-01');
  assert.equal(nextOccurrence(rules, '2026-12-31'), '2027-02-01');
  const d = deadlineView(rules.map((r) => ({ kind: 'annual_rule', ...r })), TODAY);
  assert.equal(d.text, 'Due Aug 1 · Nov 1 · Feb 1 each year');
  assert.equal(d.detail, 'Next: Nov 1, 2026');
  assert.equal(deadlineView([{ kind: 'annual_rule', annual_month: 11, annual_day: 1 }], TODAY).text, 'Due every year on Nov 1');
});

test('unknown timing is said plainly, never invented', () => {
  assert.equal(deadlineView([{ kind: 'rolling' }], TODAY).text, 'Reviewed as applications arrive');
  assert.equal(deadlineView([{ kind: 'local_administrator' }], TODAY).text, 'Dates are set locally');
  assert.equal(deadlineView([{ kind: 'unspecified', raw_text: 'not stated in the directory' }], TODAY).text, 'Deadline not listed');
  assert.equal(deadlineView([{ kind: 'unspecified', raw_text: 'closed for 2025-26; applications will open again in fall 2026' }], TODAY).text,
    'Closed for 2025-26; applications will open again in fall 2026');
  assert.equal(deadlineView([], TODAY).text, 'Deadline not listed');
});

// ------------------------------------------------------------------ fit and source
const rowOf = (over = {}) => buildRow(
  { id: 'a:1', title: 'Award', opportunity_type: 'award', provider: { name: 'Some College' }, summary: 'text', source_kind: 'official_page',
    official_url: 'https://x.example/', application_route: {}, current_cycle: { availability_status: 'open', amount: { kind: 'fixed', fixed: '1000' } },
    freshness_flags: [], review_status: 'machine_checked', last_verified_at: '2026-10-07T12:00:00Z', ...(over.list || {}) },
  { opportunity_id: 'a:1', match_status: 'needs_provider_confirmation', passed_rules: [], failed_rules: [], unknown_rules: [],
    availability_status: 'open', amount: { kind: 'fixed', fixed: '1000' }, deadlines: [], ...(over.match || {}) });

test('eligibility is described by what could be checked', () => {
  const rule = (reason) => ({ rule: 'x', unknown_reason: reason });
  assert.equal(rowOf().fit.key, 'ask');
  assert.equal(rowOf({ match: { passed_rules: [{ rule: 'ok' }], unknown_rules: [rule('source_unknown')] } }).fit.key, 'meets');
  assert.equal(rowOf({ match: { passed_rules: [{ rule: 'ok' }], unknown_rules: [rule('profile_missing')] } }).fit.key, 'more');
  assert.equal(rowOf({ match: { failed_rules: [{ rule: 'no' }] } }).fit.key, 'no');
  assert.equal(rowOf({ match: { match_status: 'not_eligible' } }).fit.key, 'no');
  assert.equal(rowOf({ match: { match_status: 'potential_fit', passed_rules: [{ rule: 'ok' }] } }).fit.key, 'fit');
  assert.deepEqual(rowOf({ match: { passed_rules: [{}, {}], unknown_rules: [rule('source_unknown'), rule('profile_missing')] } }).counts,
    { passed: 2, failed: 0, needAnswer: 1, confirm: 1 });
  assert.equal(fitView(rowOf()).tone, 'neutral');
});

test('a directory entry is never presented as the provider’s own page', () => {
  const dir = sourceView(rowOf({ list: { source_kind: 'directory_listing', summary: 'Listed in the directory (page last modified 2012-11-29).' } }));
  assert.deepEqual([dir.key, dir.tone, dir.year], ['directory', 'warn', '2012']);
  assert.match(dir.note, /not from the provider’s own page/);
  assert.equal(sourceView(rowOf()).key, 'provider');
  assert.match(sourceView(rowOf()).note, /checked Oct 7, 2026/);
  assert.equal(sourceView(rowOf({ list: { opportunity_type: 'funding_channel' } })).key, 'program');
});

// ------------------------------------------------------------------ the list
const library = () => withDeadlines([
  rowOf({ list: { id: 'a:1', title: 'Charlie Bursary' }, match: { opportunity_id: 'a:1', passed_rules: [{}, {}], amount: { kind: 'fixed', fixed: '500' } } }),
  rowOf({ list: { id: 'a:2', title: 'Alpha Award', source_kind: 'directory_listing' }, match: { opportunity_id: 'a:2', passed_rules: [{}, {}], amount: { kind: 'fixed', fixed: '9000' } } }),
  rowOf({ list: { id: 'a:3', title: 'Bravo Grant' }, match: { opportunity_id: 'a:3', match_status: 'not_eligible', failed_rules: [{}], amount: { kind: 'fixed', fixed: '3000' },
    deadlines: [{ kind: 'date', date: '2026-10-20' }] } }),
  rowOf({ list: { id: 'a:4', title: 'Delta Program', opportunity_type: 'funding_channel', provider: { name: 'Métis Nation' }, current_cycle: { availability_status: 'open', amount: null } }, match: { opportunity_id: 'a:4', passed_rules: [{}], amount: null,
    deadlines: [{ kind: 'date', date: '2026-11-01' }] } }),
], TODAY);

test('best match puts meets-what-we-can-check first, verified before directory, and not-eligible last', () => {
  const rows = library();
  const order = sortRows(rows, 'best', true).map((r) => r.title);
  assert.deepEqual(order, ['Charlie Bursary', 'Alpha Award', 'Delta Program', 'Bravo Grant']);
  assert.deepEqual(sortRows(rows, 'amount', true).map((r) => r.title), ['Alpha Award', 'Bravo Grant', 'Charlie Bursary', 'Delta Program']);
  assert.deepEqual(sortRows(rows, 'deadline', true).map((r) => r.title).slice(0, 2), ['Bravo Grant', 'Delta Program']);
  assert.deepEqual(sortRows(rows, 'name', true).map((r) => r.title), ['Alpha Award', 'Bravo Grant', 'Charlie Bursary', 'Delta Program']);
});

test('people who probably do not qualify are hidden until asked for, but only when answers were given', () => {
  const rows = library();
  assert.equal(applyFilters(rows, defaultFilters(), true).length, 3);
  assert.equal(applyFilters(rows, { ...defaultFilters(), showNo: true }, true).length, 4);
  assert.equal(applyFilters(rows, defaultFilters(), false).length, 4, 'without answers nothing is judged');
});

test('search ignores case and accents; facets combine; counts follow the other filters', () => {
  const rows = library();
  assert.deepEqual(applyFilters(rows, { ...defaultFilters(), q: 'METIS nation' }, false).map((r) => r.title), ['Delta Program']);
  assert.equal(applyFilters(rows, { ...defaultFilters(), source: new Set(['directory_listing']) }, false).length, 1);
  assert.deepEqual(applyFilters(rows, { ...defaultFilters(), amount: 'lt1000' }, false).map((r) => r.title), ['Charlie Bursary']);
  assert.deepEqual(applyFilters(rows, { ...defaultFilters(), amount: 'listed' }, false).length, 3);
  const counts = facetCounts(rows, { ...defaultFilters(), type: new Set(['award']) }, false);
  assert.equal(counts.type.award, 3, 'a facet counts as if its own selection were cleared');
  assert.equal(counts.type.funding_channel, 1);
  assert.equal(counts.source.directory_listing, 1);
});

test('rows are joined by id and keep working without a match result', () => {
  const list = [{ id: 'x', title: 'X', opportunity_type: 'award', provider: { name: 'P' }, summary: '', source_kind: 'official_page', official_url: 'u',
    application_route: {}, current_cycle: { availability_status: 'upcoming', amount: { kind: 'maximum', maximum: '100' } }, freshness_flags: [] }];
  const [joined] = joinRows(list, []);
  assert.deepEqual([joined.availability, joined.amountView.text, joined.fit.key], ['upcoming', 'Up to $100', 'ask']);
});

// ------------------------------------------------------------------ routes and sharing
test('hash routes', () => {
  assert.deepEqual(parseHash(''), { name: 'welcome', params: {} });
  assert.deepEqual(parseHash('#/'), { name: 'welcome', params: {} });
  assert.deepEqual(parseHash('#/start/3'), { name: 'start', step: 3, params: {} });
  assert.equal(parseHash('#/start/99').step, 5);
  assert.equal(parseHash('#/start/x').step, 1);
  assert.deepEqual(parseHash('#/results?sample=1'), { name: 'results', params: { sample: '1' } });
  assert.deepEqual(parseHash('#/s/' + encodeURIComponent('a:b_c')), { name: 'detail', id: 'a:b_c', params: {} });
  assert.equal(parseHash('#/about').name, 'about');
  assert.equal(parseHash('#/nope').name, 'notfound');
});

test('the shortlist can be copied as plain text', () => {
  const text = shortlistText(library().slice(0, 1), TODAY);
  assert.match(text, /Charlie Bursary \(Some College\)/);
  assert.match(text, /\$500\. Deadline not listed\./);
  assert.match(text, /Confirm every detail with the provider/);
});

test('card and detail texts', () => {
  const dir = rowOf({ list: { source_kind: 'directory_listing', summary: 'Listed in the directory (page last modified 2022-08-22). Provider: X. Field of study: Nursing. Province/territory: British Columbia. Awards available: 1. The directory states no deadline.' } });
  assert.equal(cardSummary(dir), 'Field of study: Nursing · Province or territory: British Columbia');
  assert.equal(cardSummary(rowOf({ list: { summary: 'Plain summary.' } })), 'Plain summary.');
  assert.equal(flagText('timezone_unknown'), 'The provider does not give a time zone for the deadline.');
  assert.equal(flagText('some_new_flag'), 'Some new flag.');
  assert.deepEqual(['/cycles/x/amount', '/cycles/x/deadlines/0', '/cycles/x/eligibility/mandatory/1', '/application', '/x'].map(evidenceLabel),
    ['Amount', 'Timing', 'Who can apply', 'How to apply', 'Details']);
});

test('evidence is listed once per quote, from the match or from the record', () => {
  const fromMatch = { evidence: [{ quote: 'Q1', field_path: '/application', source_url: 'https://p.example/', locator: { heading: 'How to apply' } }, { quote: 'Q1' }, { quote: '' }] };
  assert.deepEqual(evidenceList(fromMatch, null), [{ label: 'How to apply', quote: 'Q1', url: 'https://p.example/', heading: 'How to apply' }]);
  const detail = { opportunity: { evidence: [{ quote: 'Q2', field_path: '/cycles/c/amount', snapshot_id: 's1' }], source_refs: [{ snapshot_id: 's1', url: 'https://q.example/' }] } };
  assert.equal(evidenceList({ evidence: [] }, detail)[0].url, 'https://q.example/');
});

test('a detail opened directly still becomes a complete row', () => {
  const detail = {
    current_cycle_key: 'c', verification: { source_kind: 'directory_listing' },
    opportunity: { id: 'a:9', title: 'T', opportunity_type: 'award', provider: { name: 'P' }, summary: 's', official_url: 'u', application: { route_type: 'unknown' }, review_status: 'machine_checked' },
    cycles: [{ cycle_key: 'c', availability: { status: 'open' }, amount: { kind: 'fixed', fixed: '250' }, deadlines: [{ kind: 'date', date: '2026-12-01' }], eligibility: { unstructured: [{ text: 'Be kind.' }] }, freshness_flags: ['timezone_unknown'] }],
  };
  const row = rowFromDetail(detail, TODAY);
  assert.deepEqual([row.source_kind, row.availability, row.amountView.text, row.deadline.text], ['directory_listing', 'open', '$250', 'Apply by Dec 1, 2026']);
  assert.deepEqual(providerStatements(detail), ['Be kind.']);
});
test('rule sentences use names a student recognises', () => {
  const schools = [{ id: 'sfu', name: 'Simon Fraser University' }, { id: 'ubc', name: 'The University of British Columbia' }];
  assert.equal(prettyRule({ field: 'institution_id', rule: 'Institution is sfu' }, schools), 'School is Simon Fraser University');
  assert.equal(prettyRule({ field: 'institution_id', rule: 'Institution is sfu, ubc' }, schools), 'School is Simon Fraser University or The University of British Columbia');
  assert.equal(prettyRule({ field: 'institution_id', rule: 'Institution is zzz' }, schools), 'School is zzz');
  assert.equal(prettyRule({ field: 'education_level', rule: 'Education level is undergraduate' }), 'Level of study is a bachelor’s degree');
  assert.equal(prettyRule({ field: 'education_level', rule: 'Education level is one of undergraduate, masters, doctoral' }), 'Level of study is one of: a bachelor’s degree, a master’s degree, a doctoral degree');
  assert.equal(prettyRule({ field: 'residence_province', rule: 'Province of residence is BC' }), 'Province of residence is British Columbia');
  assert.equal(prettyRule({ field: 'study_status', rule: 'Study status is full-time' }), 'Studying full-time');
  assert.equal(prettyRule({ field: 'indigenous_identity', rule: 'Indigenous identity includes at least one of Inuit' }), 'Indigenous identity includes at least one of Inuit');
  assert.equal(prettyRule({ field: null, rule: 'Good academic standing is not defined on the page' }), 'Good academic standing is not defined on the page');
  assert.equal(prettyRule(null), '');
});
test('Government of Canada material carries the statement its reproduction terms ask for', () => {
  const directory = rowOf({ list: { source_kind: 'directory_listing' } });
  const text = governmentAttribution(directory, [{ url: 'https://www.sac-isc.gc.ca/eng/1/1' }]);
  assert.match(text, /“Indigenous Bursaries Search Tool”, published by Indigenous Services Canada/);
  assert.match(text, /copy of an official work published by the Government of Canada/);
  assert.match(text, /not produced in affiliation with, or with the endorsement of, the Government of Canada/);
  const channel = rowOf({ list: { title: 'Post-Secondary Student Support Program', opportunity_type: 'funding_channel' } });
  assert.match(governmentAttribution(channel, [{ url: 'https://www.sac-isc.gc.ca/eng/2/2' }]), /“Post-Secondary Student Support Program”/);
  assert.equal(governmentAttribution(directory, [{ url: 'https://www.sfu.ca/x' }]), null, 'other providers need no such statement');
  assert.equal(governmentAttribution(directory, []), null);
});
