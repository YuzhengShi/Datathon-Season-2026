// Tests for frontend/model.js: everything that turns API data into words for a student.
// The first half carries over the checks written for the first version of the web app (the logic was ported as it was);
// the second half covers what the redesigned interface added.
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const M = require('../../frontend/model.js');
const {
  OTHER_SCHOOL, UNDECIDED_SCHOOL, amountView, applyFilters, buildProfile, buildRow, daysBetween, deadlineView, defaultFilters,
  cardSummary, describeAnswers, evidenceLabel, evidenceList, fitView, flagText, formatMoney, joinRows, nextOccurrence, plainDate,
  prettyRule, providerStatements, rowFromDetail, sortRows, sourceView, urgencyText, withDeadlines, governmentAttribution,
} = M;

const TODAY = '2026-10-08';
const SCHOOLS = [{ id: 'sfu', name: 'Simon Fraser University', province: 'BC' }, { id: 'ubc', name: 'The University of British Columbia', province: 'BC' }];

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
  assert.deepEqual(buildProfile(M.blankAnswers()), {});
  assert.equal(buildProfile({ identity: ['first_nations'], fnRegistered: 'no' }).first_nations_registered, false);
  assert.equal(M.isPersonalized({}), false);
  assert.equal(M.isPersonalized({ residence_province: 'BC' }), true);
});

test('another school sends its name and province; an undecided school sends nothing about the school', () => {
  assert.deepEqual(buildProfile({ school: OTHER_SCHOOL, otherSchoolName: '  Dalhousie University ', otherSchoolProvince: 'NS' }),
    { institution_name: 'Dalhousie University', institution_province: 'NS' });
  assert.deepEqual(buildProfile({ school: UNDECIDED_SCHOOL }), {});
});

test('the answers bar uses plain words', () => {
  const a = { identity: ['inuit'], province: 'NU', level: 'undergraduate', studyStatus: 'part_time', school: 'sfu' };
  assert.deepEqual(describeAnswers(a, SCHOOLS), ['Inuit', 'Lives in Nunavut', 'University', 'Part-time', 'Simon Fraser University']);
  assert.deepEqual(M.answerChips(a, SCHOOLS).map((c) => c.key), ['identity', 'province', 'level', 'studyStatus', 'school']);
  assert.deepEqual(describeAnswers({ school: OTHER_SCHOOL, otherSchoolProvince: 'BC' }), ['Studying in British Columbia']);
  assert.deepEqual(describeAnswers({ school: OTHER_SCHOOL }), ['Another school']);
  assert.deepEqual(describeAnswers({ identity: ['first_nations', 'metis'] }), ['First Nations + Métis']);
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
    assert.equal(amountView(unclear).short, 'Not listed');
  }
  assert.equal(amountView({ kind: 'fixed', fixed: '4000' }).short, '$4,000');
});

test('when there is no single figure the provider’s own words are offered; a plain figure needs no second statement', () => {
  const words = 'Tuition and mandatory fees are supported; a books allowance of $250 per semester is stated.';
  assert.equal(M.amountWords({ kind: 'unspecified', raw_text: words }), words);
  assert.equal(M.amountWords({ kind: 'fixed', fixed: '5000', raw_text: '$5,000' }), '');
  assert.equal(M.amountWords({ kind: 'maximum', maximum: '5000', raw_text: 'up to $5,000' }), '');
  assert.equal(M.amountWords(null), '');
  assert.ok(M.amountWords({ kind: 'variable', raw_text: 'x'.repeat(900) }).length <= 320);
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

test('search ignores case and accents; type and amount filters combine', () => {
  const rows = library();
  assert.deepEqual(applyFilters(rows, { ...defaultFilters(), q: 'METIS nation' }, false).map((r) => r.title), ['Delta Program']);
  assert.equal(applyFilters(rows, { ...defaultFilters(), source: new Set(['directory_listing']) }, false).length, 1);
  assert.deepEqual(applyFilters(rows, { ...defaultFilters(), amount: 'lt1000' }, false).map((r) => r.title), ['Charlie Bursary']);
  assert.deepEqual(applyFilters(rows, { ...defaultFilters(), amount: 'mid' }, false).map((r) => r.title), ['Bravo Grant']);
  assert.deepEqual(applyFilters(rows, { ...defaultFilters(), amount: 'gt5000' }, false).map((r) => r.title), ['Alpha Award']);
  assert.deepEqual(applyFilters(rows, { ...defaultFilters(), amount: 'unknown' }, false).map((r) => r.title), ['Delta Program']);
  assert.deepEqual(applyFilters(rows, { ...defaultFilters(), amount: 'listed' }, false).length, 3);
  assert.deepEqual(applyFilters(rows, { ...defaultFilters(), type: new Set(['funding_channel']), amount: 'unknown' }, false).map((r) => r.title), ['Delta Program']);
});

test('rows are joined by id and keep working without a match result', () => {
  const list = [{ id: 'x', title: 'X', opportunity_type: 'award', provider: { name: 'P' }, summary: '', source_kind: 'official_page', official_url: 'u',
    application_route: {}, current_cycle: { availability_status: 'upcoming', amount: { kind: 'maximum', maximum: '100' } }, freshness_flags: [] }];
  const [joined] = joinRows(list, []);
  assert.deepEqual([joined.availability, joined.amountView.text, joined.fit.key], ['upcoming', 'Up to $100', 'ask']);
});

// ------------------------------------------------------------------ card and detail texts
test('card and detail texts', () => {
  const dir = rowOf({ list: { source_kind: 'directory_listing', summary: 'Listed in the directory (page last modified 2022-08-22). Provider: X. Field of study: Nursing. Province/territory: British Columbia. Awards available: 1. The directory states no deadline.' } });
  assert.equal(cardSummary(dir), 'Field of study: Nursing · Province or territory: British Columbia');
  assert.equal(cardSummary(rowOf({ list: { summary: 'Plain summary.' } })), 'Plain summary.');
  assert.equal(flagText('timezone_unknown'), 'The provider does not give a time zone for the deadline.');
  assert.equal(flagText('some_new_flag'), 'Some new flag.');
  assert.deepEqual(['/cycles/x/amount', '/cycles/x/deadlines/0', '/cycles/x/eligibility/mandatory/1', '/application', '/x'].map(evidenceLabel),
    ['Amount', 'Timing', 'Who can apply', 'How to apply', 'Details']);
});

test('every freshness flag the service can raise is said in a student’s words, and the ones the screen already shows are not repeated', () => {
  for (const flag of ['cycle_unspecified', 'timezone_unknown', 'annual_rule_unconfirmed', 'closing_time_ambiguous', 'eligibility_not_fully_structured',
    'verification_stale', 'never_verified', 'source_changed_since_verification', 'historical_cycle_only']) {
    // the generic fallback would only capitalise the flag's name ("Verification stale."): each of these has a real sentence
    assert.notEqual(flagText(flag), M.cap(flag.replace(/_/g, ' ')) + '.', flag);
  }
  assert.deepEqual(M.visibleFlags(['amount_unknown', 'deadline_unknown', 'local_administrator_deadline', 'timezone_unknown']), ['timezone_unknown']);
  assert.deepEqual(M.visibleFlags(undefined), []);
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
  assert.equal(prettyRule({ field: 'institution_id', rule: 'Institution is sfu' }, SCHOOLS), 'School is Simon Fraser University');
  assert.equal(prettyRule({ field: 'institution_id', rule: 'Institution is sfu, ubc' }, SCHOOLS), 'School is Simon Fraser University or The University of British Columbia');
  assert.equal(prettyRule({ field: 'institution_id', rule: 'Institution is zzz' }, SCHOOLS), 'School is zzz');
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

// ------------------------------------------------------------------ what the redesigned interface added
test('a provider gets a short, stable badge', () => {
  const t = (name) => M.providerBadge(name).text;
  assert.equal(t('Vancouver Island University'), 'VIU');
  assert.equal(t('Simon Fraser University'), 'SFU');
  assert.equal(t('Métis Nation British Columbia'), 'MNBC');
  assert.equal(t('Indigenous Services Canada'), 'ISC');
  assert.equal(t('AFOA Canada and Nutrien'), 'AFOA', 'an acronym that opens the name is used as it is');
  assert.equal(t('BMO Bank of Montreal and Capilano University Foundation'), 'BMO');
  assert.equal(t('B.C. Hydro'), 'BC');
  assert.equal(t('First Nations Information Governance Centre (FNIGC)'), 'FNIGC', 'an acronym in brackets wins');
  assert.equal(t('The Canadian Press'), 'CP');
  assert.equal(t('Cenovus Energy Inc.'), 'CE');
  assert.equal(t('The British Columbia Library Association, First Nations Interest Group, and the University of British Columbia'), 'BCLA',
    'a long list of partners is reduced to the first one');
  assert.ok(M.providerBadge('').text.length >= 1);
  assert.ok(t('Registered Nurses Foundation of British Columbia').length <= 4);
  assert.equal(M.providerBadge('Langara College').tone, M.providerBadge('Langara College').tone);
  assert.ok(['peach', 'sage', 'blue'].includes(M.providerBadge('Langara College').tone));
});

const ruleRow = (rules) => rowOf({ match: { unknown_rules: rules.map((r) => ({ unknown_reason: 'profile_missing', ...r })) } });

test('the communities and the place a provider names are read from the rules the service extracted', () => {
  const all = ruleRow([{ field: 'indigenous_identity', rule: 'Indigenous identity includes at least one of First Nations, Inuit, Métis' }]);
  assert.deepEqual(M.communitiesOf(all), ['First Nations', 'Inuit', 'Métis']);
  assert.deepEqual(M.communitiesOf(ruleRow([{ field: 'indigenous_identity', rule: 'Indigenous identity includes at least one of Metis' }])), ['Métis']);
  assert.deepEqual(M.communitiesOf(ruleRow([
    { field: 'indigenous_identity', rule: 'Indigenous identity includes at least one of First Nations, Inuit' },
    { field: 'indigenous_identity', rule: 'Indigenous identity includes at least one of Inuit, Métis' }])), ['Inuit'], 'two rules must both hold');
  assert.deepEqual(M.communitiesOf(ruleRow([{ field: 'study_status', rule: 'Study status is full-time' }])), [], 'no identity rule: the page names no community');
  assert.deepEqual(M.communitiesOf(ruleRow([{ field: 'indigenous_identity', rule: 'Open to everyone in the community' }])), []);

  assert.equal(M.placeOf(ruleRow([{ field: 'institution_id', rule: 'Institution is sfu' }]), SCHOOLS), 'Students at Simon Fraser University');
  assert.equal(M.placeOf(ruleRow([{ field: 'institution_id', rule: 'Institution is sfu, ubc' }]), SCHOOLS), 'Students at Simon Fraser University or The University of British Columbia');
  assert.equal(M.placeOf(ruleRow([{ field: 'institution_id', rule: 'Institution is a, b, c' }]), []), 'Students at 3 schools');
  assert.equal(M.placeOf(ruleRow([{ field: 'residence_province', rule: 'Province/territory of residence is BC' }])), 'Lives in British Columbia');
  assert.equal(M.placeOf(ruleRow([{ field: 'residence_province', rule: 'Province/territory of residence is BC' },
    { field: 'institution_province', rule: 'Province/territory of the institution is BC' }])), 'Lives in British Columbia · Studying in British Columbia');
  assert.equal(M.placeOf(ruleRow([{ field: 'education_level', rule: 'Education level is college' }])), '');
});

test('the quick filters and the questions edit the same answers', () => {
  const a = M.blankAnswers();
  assert.equal(M.communityValue(a), '');
  assert.deepEqual(M.withCommunity(a, 'inuit').identity, ['inuit']);
  assert.equal(M.communityValue(M.withCommunity(a, 'inuit')), 'inuit');
  assert.equal(M.communityValue({ ...a, identity: ['inuit', 'metis'] }), 'multi');
  assert.deepEqual(M.withCommunity({ ...a, identity: ['inuit', 'metis'] }, 'multi').identity, ['inuit', 'metis'], 'the "several" entry changes nothing');
  assert.deepEqual(M.withCommunity({ ...a, identity: ['inuit'] }, '').identity, [], 'choosing "all communities" clears the answer');
  assert.equal(a.identity.length, 0, 'answers are never changed in place');

  const sfu = M.withLocation(a, 'school:sfu');
  assert.deepEqual([sfu.school, M.locationValue(sfu)], ['sfu', 'school:sfu']);
  assert.deepEqual(buildProfile(sfu, SCHOOLS), { institution_id: 'sfu', institution_province: 'BC' });
  const ab = M.withLocation(sfu, 'prov:AB');
  assert.deepEqual([ab.school, ab.otherSchoolProvince, M.locationValue(ab)], [OTHER_SCHOOL, 'AB', 'prov:AB']);
  assert.deepEqual(buildProfile(ab), { institution_province: 'AB' });
  assert.equal(M.locationValue(M.withLocation(ab, '')), '');
  assert.deepEqual(buildProfile(M.withLocation(ab, '')), {});
});

test('"where will you study" round-trips through the answers without inventing a school', () => {
  const a = M.blankAnswers();
  assert.deepEqual(M.whereOf(a, SCHOOLS), { where: '', school: '', province: '' });
  const bcAnySchool = M.withWhere(a, { where: 'bc' });
  assert.deepEqual(buildProfile(bcAnySchool), { institution_province: 'BC' });
  assert.deepEqual(M.whereOf(bcAnySchool, SCHOOLS), { where: 'bc', school: '', province: 'BC' });
  const bcSfu = M.withWhere(a, { where: 'bc', school: 'sfu' });
  assert.deepEqual(M.whereOf(bcSfu, SCHOOLS), { where: 'bc', school: 'sfu', province: '' });
  const away = M.withWhere(a, { where: 'elsewhere', province: 'ON' });
  assert.deepEqual([M.whereOf(away).where, M.whereOf(away).province, buildProfile(away).institution_province], ['elsewhere', 'ON', 'ON']);
  assert.deepEqual(buildProfile(M.withWhere(a, { where: 'elsewhere' })), {}, 'elsewhere without a province says nothing');
  assert.deepEqual(buildProfile(M.withWhere(a, { where: 'unsure' })), {});
  assert.equal(M.whereOf(M.withWhere(a, { where: 'unsure' })).where, 'unsure');
  assert.deepEqual(buildProfile(M.withWhere(bcSfu, { where: 'unsure' })), {}, 'changing the answer forgets the school');
});

test('a goal settles the level only when it names exactly one', () => {
  const a = M.blankAnswers();
  assert.equal(M.withGoal(a, 'training').level, 'trades_vocational');
  assert.equal(M.withGoal(a, 'high_school').level, 'high_school');
  assert.equal(M.withGoal(a, 'postsecondary').level, '', 'university or college is not a single level');
  assert.equal(M.withGoal(a, 'postsecondary', 'college').level, 'college');
  assert.equal(M.withGoal(M.withGoal(a, 'postsecondary', 'college'), 'exploring').level, '');
  assert.deepEqual(buildProfile(M.withGoal(a, 'training')), { education_level: 'trades_vocational' });
  assert.equal(M.planLabel(M.withGoal(a, 'training')), 'Trades or vocational training');
  assert.equal(M.planLabel(M.withGoal(a, 'postsecondary')), 'University or college');
  assert.equal(M.planLabel(M.withGoal(a, 'postsecondary', 'undergraduate')), 'University');
  assert.equal(M.planLabel(a), '');
});

test('status answers are described only for the groups the student picked', () => {
  assert.deepEqual(M.statusAnswers({ identity: ['metis'], metisCitizen: 'yes', fnRegistered: 'yes' }), [{ label: 'Citizen of a Métis government', value: 'Yes' }]);
  assert.deepEqual(M.statusAnswers({ identity: ['first_nations'], fnRegistered: '' }), []);
  assert.deepEqual(M.statusAnswers({ identity: ['inuit'], inuitBeneficiary: 'no' }), [{ label: 'Inuit land-claim beneficiary', value: 'No' }]);
});

test('the detail view lists rules as matching, not matching, or needing someone to confirm', () => {
  const row = rowOf({ match: {
    passed_rules: [{ field: 'indigenous_identity', rule: 'Indigenous identity includes at least one of Inuit' }],
    failed_rules: [{ field: 'institution_id', rule: 'Institution is sfu' }],
    unknown_rules: [{ field: 'study_status', rule: 'Study status is full-time', unknown_reason: 'profile_missing' }, { field: null, rule: 'Good standing is judged by the provider', unknown_reason: 'source_unknown' }],
  } });
  const items = M.ruleItems(row, SCHOOLS);
  assert.deepEqual(items.map((i) => i.kind), ['pass', 'fail', 'unknown', 'unknown']);
  assert.deepEqual(items.map((i) => i.label), ['Community', 'School', 'Full-time or part-time', 'From the provider']);
  assert.equal(items[1].text, 'School is Simon Fraser University');
  assert.equal(items[2].why, 'We need an answer from you to check this.');
  assert.equal(items[3].why, 'Only the provider can confirm this.');
  const asked = M.requirementList(row, { cycles: [{ eligibility: { unstructured: [{ text: 'good standing is judged by the provider' }] } }] }, SCHOOLS);
  assert.equal(asked.length, 3, 'a sentence the provider already said is not listed a second time');
  assert.ok(asked.every((i) => i.kind === 'ask'));
});

test('next steps follow how the provider takes applications', () => {
  const row = (route, extra = {}) => rowOf({ list: { application_route: route, ...extra } });
  const titles = (steps) => steps.map((s) => s.title);
  assert.deepEqual(titles(M.nextSteps(row({ route_type: 'online_application', url: 'https://a.example/apply', instructions: 'Apply online.' }), null)),
    ['Read the provider’s page', 'Apply with the provider', 'Confirm before you apply']);
  assert.equal(M.nextSteps(row({ route_type: 'online_application', url: 'https://a.example/apply', instructions: 'Apply online.' }), null)[1].url, 'https://a.example/apply');
  assert.equal(M.nextSteps(row({ route_type: 'contact_administrator', contact_url: 'https://c.example/' }), null)[1].title, 'Contact the administrator');
  assert.equal(M.nextSteps(row({ route_type: 'institution_portal' }), null)[1].title, 'Apply through the school');
  assert.equal(M.nextSteps(row({ route_type: 'unknown' }), null)[1].title, 'Ask how to apply');
  const detail = { opportunity: { required_documents: [{ type: 'transcript', label: 'Latest transcript' }, { type: 'essay' }] }, shared_application_with: [{ id: 'x', title: 'X' }] };
  const long = M.nextSteps(row({ route_type: 'unknown', instructions: 'Ask the office.' }), detail);
  assert.deepEqual(titles(long), ['Read the provider’s page', 'How to apply', 'Prepare your documents', 'One application, several awards', 'Confirm before you apply']);
  assert.equal(long[2].text, 'Latest transcript, essay.');
  assert.match(long[3].text, /covers 1 other award\./);
});

test('the service’s advice reads without raw addresses', () => {
  assert.equal(M.plainAction('Some conditions can only be confirmed by the provider or administrator. Contact them via https://x.org/y.'),
    'Some conditions can only be confirmed by the provider or administrator. Contact them via the provider’s page.');
  assert.equal(M.plainAction('You appear to meet the recorded conditions. Review the official page and apply: https://x.org/apply'),
    'You appear to meet the recorded conditions. Review the official page and apply.');
  assert.equal(M.plainAction('Check https://x.org/ for the opening date.'), 'Check the provider’s page for the opening date.');
  assert.equal(M.plainAction(''), '');
  assert.equal(M.plainAction(null), '');
});

test('text from scraped pages can neither inject markup nor smuggle in a script link', () => {
  assert.equal(M.escapeHTML('<img src=x onerror="a()"> & \'q\''), '&lt;img src=x onerror=&quot;a()&quot;&gt; &amp; &#39;q&#39;');
  assert.equal(M.escapeHTML(null), '');
  assert.equal(M.escapeHTML(42), '42');
  assert.equal(M.safeUrl('https://afoa.ca/awards/youth/'), 'https://afoa.ca/awards/youth/');
  assert.equal(M.safeUrl('  http://example.org/x '), 'http://example.org/x');
  for (const bad of ['javascript:alert(1)', 'data:text/html,x', '//evil.example/', '/relative', 'ftp://x.example/', '', null, undefined, 'https://']) {
    assert.equal(M.safeUrl(bad), '', String(bad));
  }
  assert.equal(M.hostOf('https://www.sfu.ca/awards'), 'sfu.ca');
  assert.equal(M.hostOf('nonsense'), '');
});

test('hash routes name a view or one opportunity', () => {
  assert.deepEqual(M.parseRoute(''), { view: '' });
  assert.deepEqual(M.parseRoute('#explore'), { view: 'explore' });
  assert.deepEqual(M.parseRoute('#saved'), { view: 'saved' });
  const id = 'afoa_canada_and_nutrien:isc_nutrien/awards ?x';
  assert.deepEqual(M.parseRoute(M.programHash(id)), { view: 'program', id });
  assert.equal(M.programHash('a:b'), '#program/a%3Ab');
  assert.deepEqual(M.parseRoute('#program/'), { view: 'explore' });
  assert.deepEqual(M.parseRoute('#program/%E0%A4%A'), { view: 'program', id: '%E0%A4%A' }, 'a malformed escape is used as written');
});

test('the illustration and the data tag fit the kind of support and the data mode', () => {
  assert.equal(M.artFor(rowOf({ list: { opportunity_type: 'funding_channel' } })).asset, 'paper-portfolio');
  assert.equal(M.artFor(rowOf({ list: { title: 'MNBC STEPS - Education and Skills Training Funding' } })).asset, 'skills-path');
  assert.equal(M.artFor(rowOf({ list: { title: 'Entrance Scholarship' } })).asset, 'study-kit');
  assert.equal(M.dataTag('live', '2026-10-08T12:00:00Z'), 'Checked Oct 8, 2026');
  assert.equal(M.dataTag('live', ''), 'Official sources');
  assert.equal(M.dataTag('demo', '2026-10-08T12:00:00Z'), 'Demo · Made-up data');
  assert.equal(M.lastCheckedOf([{ lastVerified: '2026-10-07T12:00:00Z' }, { lastVerified: null }, { lastVerified: '2026-10-08T12:00:00Z' }]), '2026-10-08T12:00:00Z');
  assert.equal(M.lastCheckedOf([]), '');
});

test('a large figure keeps its qualifier in small type: "up to" and "in total" are moved, never dropped', () => {
  const parts = (amount) => M.amountParts(M.amountView(amount));
  assert.deepEqual(parts({ kind: 'fixed', fixed: '5000' }), { figure: '$5,000', note: 'Listed value' });
  assert.deepEqual(parts({ kind: 'maximum', maximum: '5000' }), { figure: '$5,000', note: 'Up to · maximum, not guaranteed' });
  assert.deepEqual(parts({ kind: 'pooled_total', pooled_total: '20000' }), { figure: '$20,000', note: 'In total · shared between recipients' });
  assert.deepEqual(parts({ kind: 'range', minimum: '500', maximum: '1000' }), { figure: '$500–$1,000', note: 'Listed range' });
  assert.deepEqual(parts({ kind: 'variable' }), { figure: 'Varies', note: 'Depends on the applicant' });
  assert.deepEqual(parts(null), { figure: 'Not listed', note: 'Ask the provider' });
  for (const amount of [{ kind: 'maximum', maximum: '300' }, { kind: 'pooled_total', pooled_total: '9000' }]) {
    const view = M.amountView(amount);
    const { figure, note } = M.amountParts(view);
    assert.ok(/^\$[\d,]+$/.test(figure), 'only the figure is set large');
    assert.ok(/^(Up to|In total)/.test(note), 'the qualifier that makes a listed figure honest is still on screen: ' + view.text);
  }
});

test('study plans are the levels and the full-time or part-time wish the provider names', () => {
  const rows = (rules) => rowOf({ match: { unknown_rules: rules.map((r) => ({ unknown_reason: 'profile_missing', ...r })) } });
  assert.deepEqual(M.levelsOf(rows([{ field: 'education_level', rule: 'Education level is undergraduate' }])), ['Bachelor’s degree']);
  assert.deepEqual(M.levelsOf(rows([{ field: 'education_level', rule: 'Education level is one of college, undergraduate, masters' }])), ['College', 'Bachelor’s degree', 'Master’s degree']);
  assert.deepEqual(M.levelsOf(rows([{ field: 'education_level', rule: 'Education level is one of college, undergraduate' }, { field: 'education_level', rule: 'Education level is undergraduate' }])), ['Bachelor’s degree'], 'two rules must both hold');
  assert.deepEqual(M.levelsOf(rows([{ field: 'education_level', rule: 'Education level is something new' }])), []);
  assert.deepEqual(M.levelsOf(rows([{ field: 'study_status', rule: 'Study status is full-time' }])), []);
  assert.deepEqual(M.plansOf(rows([{ field: 'education_level', rule: 'Education level is undergraduate' }, { field: 'study_status', rule: 'Study status is full-time' }])), ['Bachelor’s degree', 'Full-time']);
  assert.deepEqual(M.plansOf(rows([{ field: 'study_status', rule: 'Study status is part-time' }])), ['Part-time']);
  assert.deepEqual(M.plansOf(rows([])), []);
});
