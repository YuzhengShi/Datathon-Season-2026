// Pure logic of the web app: no DOM, no network. Tested with `node --test tests/js`.
// Everything that turns API data into words for a student lives here, so it can be checked.

export const PROVINCES = [
  ['AB', 'Alberta'], ['BC', 'British Columbia'], ['MB', 'Manitoba'], ['NB', 'New Brunswick'],
  ['NL', 'Newfoundland and Labrador'], ['NS', 'Nova Scotia'], ['NT', 'Northwest Territories'], ['NU', 'Nunavut'],
  ['ON', 'Ontario'], ['PE', 'Prince Edward Island'], ['QC', 'Québec'], ['SK', 'Saskatchewan'], ['YT', 'Yukon'],
];
export const LEVELS = [
  ['high_school', 'High school', 'Finishing high school and planning what comes next'],
  ['trades_vocational', 'Trades or vocational training', 'Apprenticeships, certificates, trades programs'],
  ['college', 'College', 'Diploma or certificate'],
  ['undergraduate', 'University: bachelor’s degree', ''],
  ['masters', 'Master’s degree', ''],
  ['doctoral', 'Doctoral degree', ''],
];
export const IDENTITIES = [['first_nations', 'First Nations'], ['inuit', 'Inuit'], ['metis', 'Métis']];
export const SAMPLE_ANSWERS = {
  identity: ['first_nations'], fnRegistered: 'yes', metisCitizen: '', inuitBeneficiary: '', province: 'BC', level: 'undergraduate',
  studyStatus: 'full_time', school: 'sfu', otherSchoolName: '', otherSchoolProvince: '',
};
export const OTHER_SCHOOL = '__other__';
export const UNDECIDED_SCHOOL = '__undecided__';

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const pad = (n) => String(n).padStart(2, '0');
const labelOf = (pairs, key) => (pairs.find(([k]) => k === key) || [])[1] || key;
export const provinceName = (code) => labelOf(PROVINCES, code);
export const levelName = (key) => labelOf(LEVELS, key);

export const fold = (text) => String(text || '').normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase();
export const cap = (text) => (text ? text[0].toUpperCase() + text.slice(1) : '');
export const clamp = (text, n) => (text.length > n ? text.slice(0, n - 1).trimEnd() + '…' : text);

// ---------------------------------------------------------------- the profile (answers -> request body)
const yesNo = (value) => (value === 'yes' ? true : value === 'no' ? false : undefined);

/** Only what the student actually answered is sent; "not sure" and skipped questions stay absent (= unknown, never "no"). */
export function buildProfile(a, institutions = []) {
  const p = {};
  const identity = (a.identity || []).filter((x) => IDENTITIES.some(([k]) => k === x));
  if (identity.length) {
    p.indigenous_identity = identity;
    if (identity.includes('first_nations') && yesNo(a.fnRegistered) !== undefined) p.first_nations_registered = yesNo(a.fnRegistered);
    if (identity.includes('metis') && yesNo(a.metisCitizen) !== undefined) p.metis_citizen = yesNo(a.metisCitizen);
    if (identity.includes('inuit') && yesNo(a.inuitBeneficiary) !== undefined) p.inuit_beneficiary = yesNo(a.inuitBeneficiary);
  }
  if (a.province) p.residence_province = a.province;
  if (a.level) p.education_level = a.level;
  if (a.studyStatus) p.study_status = a.studyStatus;
  if (a.school && a.school !== OTHER_SCHOOL && a.school !== UNDECIDED_SCHOOL) {
    p.institution_id = a.school;
    const school = institutions.find((i) => i.id === a.school);
    if (school && school.province) p.institution_province = school.province;
  } else if (a.school === OTHER_SCHOOL) {
    const name = (a.otherSchoolName || '').trim();
    if (name) p.institution_name = name.slice(0, 200);
    if (a.otherSchoolProvince) p.institution_province = a.otherSchoolProvince;
  }
  return p;
}

export const isPersonalized = (profile) => Object.keys(profile || {}).length > 0;

/** Short labels for the "your answers" bar. */
export function describeAnswers(a, institutions = []) {
  const out = [];
  const names = (a.identity || []).map((k) => labelOf(IDENTITIES, k));
  if (names.length) out.push(names.join(' + '));
  if (a.province) out.push('Lives in ' + provinceName(a.province));
  if (a.level) out.push(labelOf(LEVELS, a.level).replace(/: .*/, ''));
  if (a.studyStatus) out.push(a.studyStatus === 'full_time' ? 'Full-time' : 'Part-time');
  if (a.school === OTHER_SCHOOL) out.push(a.otherSchoolName ? a.otherSchoolName.trim() : 'Another school');
  else if (a.school && a.school !== UNDECIDED_SCHOOL) out.push((institutions.find((i) => i.id === a.school) || {}).name || a.school);
  return out;
}

// ---------------------------------------------------------------- money, dates
export function formatMoney(value) {
  const n = Number(value);
  if (value === null || value === undefined || value === '' || !Number.isFinite(n)) return null;
  const cents = Math.abs(n % 1) > 0;
  return '$' + n.toLocaleString('en-CA', { minimumFractionDigits: cents ? 2 : 0, maximumFractionDigits: 2 });
}

/** The "price" of a scholarship: always what the provider LISTS, never a promise. */
export function amountView(amount) {
  const none = { text: 'Amount not listed', kind: 'unknown', value: null, note: '' };
  if (!amount) return none;
  const money = (v) => formatMoney(v);
  switch (amount.kind) {
    case 'fixed':
      return money(amount.fixed) ? { text: money(amount.fixed), kind: 'fixed', value: Number(amount.fixed), note: 'listed value' } : none;
    case 'maximum':
      return money(amount.maximum) ? { text: 'Up to ' + money(amount.maximum), kind: 'maximum', value: Number(amount.maximum), note: 'maximum, not guaranteed' } : none;
    case 'range':
      return money(amount.minimum) && money(amount.maximum)
        ? { text: money(amount.minimum) + '–' + money(amount.maximum), kind: 'range', value: Number(amount.maximum), note: 'listed range' } : none;
    case 'pooled_total':
      return money(amount.pooled_total) ? { text: money(amount.pooled_total) + ' in total', kind: 'pooled', value: Number(amount.pooled_total), note: 'shared between recipients' } : none;
    case 'variable':
      return { text: 'Varies', kind: 'variable', value: null, note: 'depends on the applicant' };
    default:
      return none;
  }
}

export function plainDate(iso) {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso || '');
  return m ? `${MONTHS[Number(m[2]) - 1]} ${Number(m[3])}, ${m[1]}` : null;
}
export function isoDate(date) {
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}
export function daysBetween(fromIso, toIso) {
  const part = (s) => { const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(s); return Date.UTC(Number(m[1]), Number(m[2]) - 1, Number(m[3])); };
  return Math.round((part(toIso) - part(fromIso)) / 86400000);
}
export function nextOccurrence(rules, todayIso) {
  const year = Number(todayIso.slice(0, 4));
  let best = null;
  for (const r of rules) {
    for (const y of [year, year + 1]) {
      const iso = `${y}-${pad(r.annual_month)}-${pad(r.annual_day)}`;
      if (iso >= todayIso && (best === null || iso < best)) best = iso;
    }
  }
  return best;
}
export function urgencyText(days) {
  if (days === null || days === undefined || days < 0) return null;
  return days === 0 ? 'Closes today' : days === 1 ? 'Closes tomorrow' : `Closes in ${days} days`;
}

/** What to tell a student about timing. Dates are shown as written by the provider; time zones are never guessed. */
export function deadlineView(deadlines, todayIso) {
  const list = deadlines || [];
  const dated = list.filter((d) => (d.kind === 'date' || d.kind === 'datetime') && d.date).sort((a, b) => a.date.localeCompare(b.date));
  if (dated.length) {
    const pick = dated.find((d) => d.date >= todayIso) || dated[dated.length - 1];
    const closed = pick.date < todayIso || (pick.closing && pick.closing.state === 'closed');
    const days = closed ? null : daysBetween(todayIso, pick.date);
    const at = pick.local_time ? ` at ${pick.local_time}` : '';
    const zoneUnknown = pick.closing && (pick.closing.flags || []).includes('timezone_unknown');
    return {
      kind: 'date', closed: Boolean(closed), days, soon: days !== null && days <= 14, sortKey: pick.date,
      text: closed ? `Closed ${plainDate(pick.date)}` : `Apply by ${plainDate(pick.date)}${at}`,
      detail: zoneUnknown ? 'The provider does not give a time zone' : '',
    };
  }
  const annual = list.filter((d) => d.kind === 'annual_rule' && d.annual_month && d.annual_day);
  if (annual.length) {
    const labels = annual.map((d) => `${MONTHS[d.annual_month - 1]} ${d.annual_day}`);
    const next = nextOccurrence(annual, todayIso);
    const days = next ? daysBetween(todayIso, next) : null;
    return {
      kind: 'annual', closed: false, days, soon: days !== null && days <= 14, sortKey: next,
      text: annual.length === 1 ? `Due every year on ${labels[0]}` : `Due ${labels.join(' · ')} each year`,
      detail: next ? `Next: ${plainDate(next)}` : '',
    };
  }
  if (list.some((d) => d.kind === 'rolling')) {
    return { kind: 'rolling', closed: false, days: null, soon: false, sortKey: null, text: 'Reviewed as applications arrive', detail: 'No closing date listed' };
  }
  if (list.some((d) => d.kind === 'local_administrator')) {
    return { kind: 'local', closed: false, days: null, soon: false, sortKey: null, text: 'Dates are set locally', detail: 'Ask your band office or the administrator' };
  }
  const note = (list.find((d) => d.raw_text && !/^not stated/i.test(d.raw_text)) || {}).raw_text;
  return {
    kind: 'unknown', closed: false, days: null, soon: false, sortKey: null,
    text: note ? cap(note) : 'Deadline not listed', detail: note ? '' : 'Check the provider’s page',
  };
}

// ---------------------------------------------------------------- how well does it fit, where does it come from
const AVAILABILITY = {
  open: ['Open now', 'good'], upcoming: ['Opens soon', 'info'], contact_administrator: ['Ask the administrator', 'neutral'],
  unknown: ['Dates not confirmed', 'neutral'], closed: ['Closed', 'muted'],
};
export const availabilityView = (status) => { const [label, tone] = AVAILABILITY[status] || AVAILABILITY.unknown; return { label, tone }; };

export function ruleCounts(row) {
  const unknown = row.unknown || [];
  const needAnswer = unknown.filter((r) => r.unknown_reason === 'profile_missing').length;
  return { passed: (row.passed || []).length, failed: (row.failed || []).length, needAnswer, confirm: unknown.length - needAnswer };
}

/** One honest sentence about eligibility. A rule nobody can check from a profile is "ask the provider", not "no". */
export function fitView(row) {
  const c = row.counts;
  if (row.status === 'not_eligible' || c.failed > 0) return { key: 'no', label: 'Probably not eligible', tone: 'muted', rank: 4 };
  if (row.status === 'potential_fit') return { key: 'fit', label: 'Looks like a fit', tone: 'good', rank: 0 };
  if (c.needAnswer > 0) return { key: 'more', label: 'More answers would help', tone: 'info', rank: 2 };
  if (c.passed > 0) return { key: 'meets', label: 'Meets what we can check', tone: 'good', rank: 1 };
  return { key: 'ask', label: 'Ask the provider about eligibility', tone: 'neutral', rank: 3 };
}

export function sourceView(row) {
  if (row.source_kind === 'directory_listing') {
    const m = /last modified (\d{4})/.exec(row.summary || '');
    return {
      key: 'directory', tone: 'warn', label: 'Government directory entry', year: m ? m[1] : null,
      note: m ? `Taken from a federal directory page last updated in ${m[1]}, not from the provider’s own page. Confirm everything with the provider.`
        : 'Taken from a federal directory, not from the provider’s own page. Confirm everything with the provider.',
    };
  }
  const checked = row.lastVerified ? `, checked ${plainDate(row.lastVerified)}` : '';
  if (row.type === 'funding_channel') return { key: 'program', tone: 'good', label: 'Official program page', note: `Read from the program’s own page${checked}.` };
  return { key: 'provider', tone: 'good', label: 'Checked on the provider’s page', note: `Read from the provider’s own page${checked}.` };
}

export function categoryOf(row) {
  if (row.type === 'funding_channel') return 'program';
  const p = row.provider || '';
  if (/(universit|college|institute|polytechnic|school)/i.test(p)) return 'school';
  if (/(foundation|fund\b|council|association|centre|center|society|nation|friendship|library)/i.test(p)) return 'community';
  if (/(bank|hydro|rail|energy|inc\b|ltd|corp|press|nutrien|bmo|cenovus|company)/i.test(p)) return 'business';
  return 'award';
}

// ---------------------------------------------------------------- joining the two API answers
export function buildRow(listItem, match) {
  const cycle = listItem.current_cycle || {};
  const row = {
    id: listItem.id, title: listItem.title, type: listItem.opportunity_type,
    provider: (listItem.provider && listItem.provider.name) || '', donor: (listItem.provider && listItem.provider.donor_name) || null,
    summary: listItem.summary || '', source_kind: listItem.source_kind || 'official_page', officialUrl: listItem.official_url,
    route: listItem.application_route || {}, lastVerified: listItem.last_verified_at || null, flags: listItem.freshness_flags || [],
    reviewStatus: listItem.review_status,
    availability: (match && match.availability_status) || cycle.availability_status || 'unknown',
    status: match ? match.match_status : null,
    amount: (match && match.amount) || cycle.amount || null,
    deadlines: (match && match.deadlines) || [],
    passed: (match && match.passed_rules) || [], failed: (match && match.failed_rules) || [], unknown: (match && match.unknown_rules) || [],
    evidence: (match && match.evidence_refs) || [], uncertainties: (match && match.source_uncertainties) || [],
    questions: (match && match.clarification_questions) || [], missing: (match && match.missing_profile_fields) || [],
    preferences: (match && match.preference_matches) || [], funderConditions: (match && match.funder_side_conditions) || [],
    nextAction: (match && match.next_action) || '', cycleKey: (match && match.cycle_key) || cycle.cycle_key || '',
  };
  row.amountView = amountView(row.amount);
  row.counts = ruleCounts(row);
  row.fit = match ? fitView(row) : { key: 'ask', label: 'Ask the provider about eligibility', tone: 'neutral', rank: 3 };
  row.category = categoryOf(row);
  return row;
}
export function joinRows(listItems, matchItems) {
  const byId = new Map((matchItems || []).map((m) => [m.opportunity_id, m]));
  return listItems.map((l) => buildRow(l, byId.get(l.id)));
}

// ---------------------------------------------------------------- filters and sorting
export const defaultFilters = () => ({ q: '', fit: new Set(), type: new Set(), source: new Set(), avail: new Set(), amount: 'any', showNo: false });

const AMOUNT_TESTS = {
  any: () => true,
  listed: (v) => v !== null,
  lt1000: (v) => v !== null && v < 1000,
  mid: (v) => v !== null && v >= 1000 && v <= 5000,
  gt5000: (v) => v !== null && v > 5000,
};
export const AMOUNT_BUCKETS = [['any', 'Any amount'], ['listed', 'Amount is listed'], ['lt1000', 'Under $1,000'], ['mid', '$1,000 to $5,000'], ['gt5000', 'Over $5,000']];

export function matchesQuery(row, q) {
  const terms = fold(q).split(/\s+/).filter(Boolean);
  if (!terms.length) return true;
  const hay = fold([row.title, row.provider, row.donor, row.summary].join(' '));
  return terms.every((t) => hay.includes(t));
}

export function applyFilters(rows, f, personalized) {
  return rows.filter((r) =>
    matchesQuery(r, f.q)
    && (f.type.size === 0 || f.type.has(r.type))
    && (f.source.size === 0 || f.source.has(r.source_kind))
    && (f.avail.size === 0 || f.avail.has(r.availability))
    && (f.fit.size === 0 || f.fit.has(r.fit.key))
    && (AMOUNT_TESTS[f.amount] || AMOUNT_TESTS.any)(r.amountView.value)
    && (f.showNo || !personalized || r.fit.key !== 'no'));
}

/** Counts for a facet are taken with every OTHER filter applied, so the numbers always match what a click would show. */
export function facetCounts(rows, f, personalized) {
  const clear = { type: new Set(), source: new Set(), avail: new Set(), fit: new Set() };
  const count = (facet, valueOf) => {
    const out = {};
    for (const r of applyFilters(rows, { ...f, [facet]: clear[facet] }, personalized)) out[valueOf(r)] = (out[valueOf(r)] || 0) + 1;
    return out;
  };
  return {
    type: count('type', (r) => r.type), source: count('source', (r) => r.source_kind),
    avail: count('avail', (r) => r.availability), fit: count('fit', (r) => r.fit.key),
  };
}

export const SORTS = [['best', 'Best match'], ['deadline', 'Deadline: soonest'], ['amount', 'Amount: high to low'], ['name', 'Name: A to Z']];
const AVAIL_RANK = { open: 0, upcoming: 1, contact_administrator: 2, unknown: 3, closed: 4 };

export function sortRows(rows, how, personalized) {
  const name = (a, b) => a.title.localeCompare(b.title);
  const by = {
    best: (a, b) => {
      const key = (r) => [personalized ? r.fit.rank : 0, personalized ? -r.counts.passed : 0, AVAIL_RANK[r.availability] ?? 3,
        r.source_kind === 'directory_listing' ? 1 : 0, -(r.amountView.value || 0)];
      const [ka, kb] = [key(a), key(b)];
      for (let i = 0; i < ka.length; i += 1) if (ka[i] !== kb[i]) return ka[i] - kb[i];
      return name(a, b);
    },
    deadline: (a, b) => {
      const [ka, kb] = [a.deadlineSort || null, b.deadlineSort || null];
      if (ka === kb) return name(a, b);
      if (ka === null) return 1;
      if (kb === null) return -1;
      return ka.localeCompare(kb);
    },
    amount: (a, b) => (b.amountView.value || -1) - (a.amountView.value || -1) || name(a, b),
    name,
  };
  return [...rows].sort(by[how] || by.best);
}

/** Cards and the "deadline" sort need the dated view once; keep it on the row. */
export function withDeadlines(rows, todayIso) {
  for (const r of rows) { r.deadline = deadlineView(r.deadlines, todayIso); r.deadlineSort = r.deadline.sortKey; }
  return rows;
}

// ---------------------------------------------------------------- the detail page when there is no match result
const FIELD_WORDS = {
  indigenous_identity: 'Indigenous identity', first_nations_registered: 'Registered First Nations person', metis_citizen: 'Métis citizenship',
  inuit_beneficiary: 'Inuit land-claim beneficiary', residence_province: 'Province you live in', institution_id: 'School',
  institution_province: 'Province of the school', education_level: 'Level of study', study_status: 'Full-time or part-time',
};
export const fieldWords = (field) => FIELD_WORDS[field] || null;

// ---------------------------------------------------------------- routing and sharing
export function parseHash(hash) {
  const raw = String(hash || '').replace(/^#\/?/, '');
  const [path, query = ''] = raw.split('?');
  const parts = path.split('/').filter(Boolean).map((p) => { try { return decodeURIComponent(p); } catch { return p; } });
  const params = Object.fromEntries(new URLSearchParams(query));
  const [head, ...rest] = parts;
  if (head === undefined) return { name: 'welcome', params };
  if (head === 'start') return { name: 'start', step: Math.min(Math.max(Number(rest[0]) || 1, 1), 5), params };
  if (head === 'results') return { name: 'results', params };
  if (head === 's' && rest.length) return { name: 'detail', id: rest.join('/'), params };
  if (head === 'about') return { name: 'about', params };
  return { name: 'notfound', params };
}
export const detailHash = (id) => `#/s/${encodeURIComponent(id)}`;

export function shortlistText(rows, todayIso) {
  const lines = ['My funding shortlist', ''];
  for (const r of rows) {
    const d = r.deadline || deadlineView(r.deadlines, todayIso);
    lines.push(`- ${r.title} (${r.provider})`, `  ${r.amountView.text}. ${d.text}.`, `  ${(r.route && r.route.url) || r.officialUrl}`);
  }
  lines.push('', 'Confirm every detail with the provider before you apply.');
  return lines.join('\n');
}

// ---------------------------------------------------------------- texts for cards and the detail page
/** Directory entries repeat a long boilerplate sentence; a card only needs what is specific to the award. */
export function cardSummary(row) {
  const s = row.summary || '';
  if (row.source_kind === 'directory_listing') {
    const field = /Field of study: ([^.]+)\./.exec(s);
    const where = /Province\/territory: ([^.]+)\./.exec(s);
    const bits = [field && `Field of study: ${field[1]}`, where && `Province or territory: ${where[1]}`].filter(Boolean);
    return bits.length ? bits.join(' · ') : clamp(s, 160);
  }
  return s;
}

const FLAGS = {
  cycle_unspecified: 'The provider does not say which year or intake this applies to.',
  timezone_unknown: 'The provider does not give a time zone for the deadline.',
  stale: 'This information has not been re-checked recently.',
  source_modified_old: 'The page this comes from has not been updated for a long time.',
};
export const flagText = (flag) => FLAGS[flag] || cap(String(flag).replace(/_/g, ' ')) + '.';

export function evidenceLabel(path = '') {
  if (path.includes('/amount')) return 'Amount';
  if (path.includes('/deadlines') || path.includes('/window')) return 'Timing';
  if (path.includes('/eligibility')) return 'Who can apply';
  if (path.startsWith('/application')) return 'How to apply';
  return 'Details';
}

function evidenceFromRecord(detail) {
  if (!detail || !detail.opportunity) return [];
  const urls = new Map((detail.opportunity.source_refs || []).map((s) => [s.snapshot_id, s.url]));
  return (detail.opportunity.evidence || []).map((e) => ({ ...e, source_url: e.source_url || urls.get(e.snapshot_id) }));
}

/** The quotes behind what is shown, from /match when there is one, otherwise from the record itself. One entry per quote. */
export function evidenceList(row, detail) {
  const refs = row.evidence && row.evidence.length ? row.evidence : evidenceFromRecord(detail);
  const seen = new Set();
  const out = [];
  for (const e of refs) {
    if (!e.quote || seen.has(e.quote)) continue;
    seen.add(e.quote);
    out.push({ label: evidenceLabel(e.field_path), quote: e.quote, url: e.source_url || '', heading: (e.locator && e.locator.heading) || '' });
  }
  return out;
}

/** The provider's own eligibility sentences (the ones no rule engine can check). */
export function providerStatements(detail) {
  const cycle = ((detail && detail.cycles) || [])[0];
  return ((cycle && cycle.eligibility && cycle.eligibility.unstructured) || []).map((u) => u.text).filter(Boolean);
}

/** A row built from the detail endpoint alone (a link opened directly, with no answers given). */
export function rowFromDetail(detail, todayIso) {
  const rec = detail.opportunity;
  const cycle = (detail.cycles || []).find((c) => c.cycle_key === detail.current_cycle_key) || (detail.cycles || [])[0] || {};
  const row = buildRow({
    id: rec.id, title: rec.title, opportunity_type: rec.opportunity_type, provider: rec.provider, summary: rec.summary,
    source_kind: (detail.verification && detail.verification.source_kind) || 'official_page', official_url: rec.official_url,
    application_route: rec.application, current_cycle: { cycle_key: cycle.cycle_key, availability_status: cycle.availability && cycle.availability.status, amount: cycle.amount },
    freshness_flags: cycle.freshness_flags || [], review_status: rec.review_status, last_verified_at: rec.last_verified_at,
  }, null);
  row.deadlines = cycle.deadlines || [];
  return withDeadlines([row], todayIso)[0];
}
// ---------------------------------------------------------------- rule sentences in a student's words
const LEVEL_WORDS = { high_school: 'high school', trades_vocational: 'trades or vocational training', college: 'college', undergraduate: 'a bachelor’s degree', masters: 'a master’s degree', doctoral: 'a doctoral degree' };

/** The service describes rules with internal ids ("Institution is sfu"); a student should read names. */
export function prettyRule(rule, institutions = []) {
  const text = String((rule && rule.rule) || '');
  const field = rule && rule.field;
  if (field === 'institution_id') {
    const m = /^Institution is (.+)$/.exec(text);
    if (!m) return text;
    return 'School is ' + m[1].split(/,\s*|\s+or\s+/).map((id) => (institutions.find((i) => i.id === id) || {}).name || id).join(' or ');
  }
  if (field === 'education_level') {
    const m = /^Education level is (?:one of )?(.+)$/.exec(text);
    if (!m) return text;
    const names = m[1].split(/,\s*/).map((k) => LEVEL_WORDS[k.trim()] || k.trim());
    return 'Level of study is ' + (names.length > 1 ? 'one of: ' : '') + names.join(', ');
  }
  if (field === 'residence_province' || field === 'institution_province') {
    return text.replace(/\b([A-Z]{2})\b/g, (code) => (PROVINCES.some(([c]) => c === code) ? provinceName(code) : code));
  }
  if (field === 'study_status') return text.replace(/^Study status is /, 'Studying ');
  return text;
}
// ---------------------------------------------------------------- what the Government of Canada's reproduction terms ask us to say
/** Non-commercial reproduction is allowed if the copy says it is a copy of an official work and is not endorsed by the Government. */
export function governmentAttribution(row, quotes) {
  const fromCanada = (quotes || []).some((q) => /^https?:\/\/(www\.)?sac-isc\.gc\.ca\//.test(q.url || ''));
  if (!fromCanada) return null;
  const material = row.source_kind === 'directory_listing' ? 'Indigenous Bursaries Search Tool' : row.title;
  return `Contains information from “${material}”, published by Indigenous Services Canada. This is a copy of an official work published by the Government of Canada; it was not produced in affiliation with, or with the endorsement of, the Government of Canada.`;
}
