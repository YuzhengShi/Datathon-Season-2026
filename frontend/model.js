// Pure logic of the web app: no DOM, no network. Tested with `node --test tests/js`.
// Everything that turns API data into words for a student lives here, so it can be checked.
// The honesty rules of the first version are kept as they were: a listed amount is never a promise, a rule nobody can check
// from a profile is "ask the provider" (never "no"), and a government directory entry is never passed off as the provider's page.
(function (root, factory) {
  'use strict';
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  root.FundingModel = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

  const PROVINCES = [
    ['AB', 'Alberta'], ['BC', 'British Columbia'], ['MB', 'Manitoba'], ['NB', 'New Brunswick'],
    ['NL', 'Newfoundland and Labrador'], ['NS', 'Nova Scotia'], ['NT', 'Northwest Territories'], ['NU', 'Nunavut'],
    ['ON', 'Ontario'], ['PE', 'Prince Edward Island'], ['QC', 'Québec'], ['SK', 'Saskatchewan'], ['YT', 'Yukon'],
  ];
  const LEVELS = [
    ['high_school', 'High school', 'Finishing high school and planning what comes next'],
    ['trades_vocational', 'Trades or vocational training', 'Apprenticeships, certificates, trades programs'],
    ['college', 'College', 'Diploma or certificate'],
    ['undergraduate', 'University: bachelor’s degree', ''],
    ['masters', 'Master’s degree', ''],
    ['doctoral', 'Doctoral degree', ''],
  ];
  const IDENTITIES = [['first_nations', 'First Nations'], ['inuit', 'Inuit'], ['metis', 'Métis']];
  const OTHER_SCHOOL = '__other__';
  const UNDECIDED_SCHOOL = '__undecided__';

  const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  const pad = (n) => String(n).padStart(2, '0');
  const labelOf = (pairs, key) => (pairs.find(([k]) => k === key) || [])[1] || key;
  const provinceName = (code) => labelOf(PROVINCES, code);
  const levelName = (key) => labelOf(LEVELS, key);

  const fold = (text) => String(text || '').normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase();
  const cap = (text) => (text ? text[0].toUpperCase() + text.slice(1) : '');
  const clamp = (text, n) => (text.length > n ? text.slice(0, n - 1).trimEnd() + '…' : text);
  const escapeHTML = (value) => String(value === null || value === undefined ? '' : value)
    .replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  /** Links come from scraped pages: only plain http(s) addresses may become a link. */
  function safeUrl(url) {
    const text = String(url || '').trim();
    if (!/^https?:\/\//i.test(text)) return '';
    try { new URL(text); return text; } catch { return ''; }
  }
  function hostOf(url) {
    try { return new URL(url).hostname.replace(/^www\./, ''); } catch { return ''; }
  }

  // ---------------------------------------------------------------- the answers (what the questions edit)
  const blankAnswers = () => ({
    identity: [], fnRegistered: '', metisCitizen: '', inuitBeneficiary: '', province: '', level: '', studyStatus: '',
    school: '', otherSchoolName: '', otherSchoolProvince: '', goal: '',
  });
  const cloneAnswers = (a) => ({ ...blankAnswers(), ...a, identity: [...((a && a.identity) || [])] });

  const yesNo = (value) => (value === 'yes' ? true : value === 'no' ? false : undefined);

  /** Only what the student actually answered is sent; "not sure" and skipped questions stay absent (= unknown, never "no"). */
  function buildProfile(a, institutions = []) {
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

  const isPersonalized = (profile) => Object.keys(profile || {}).length > 0;

  /** The answers as short labelled pieces. `key` says which answer a piece belongs to. */
  function answerChips(a, institutions = []) {
    const out = [];
    const names = (a.identity || []).map((k) => labelOf(IDENTITIES, k));
    if (names.length) out.push({ key: 'identity', label: names.join(' + ') });
    if (a.province) out.push({ key: 'province', label: 'Lives in ' + provinceName(a.province) });
    if (a.level) out.push({ key: 'level', label: labelOf(LEVELS, a.level).replace(/: .*/, '') });
    if (a.studyStatus) out.push({ key: 'studyStatus', label: a.studyStatus === 'full_time' ? 'Full-time' : 'Part-time' });
    if (a.school === OTHER_SCHOOL) {
      const name = (a.otherSchoolName || '').trim();
      if (name) out.push({ key: 'school', label: name });
      else if (a.otherSchoolProvince) out.push({ key: 'school', label: 'Studying in ' + provinceName(a.otherSchoolProvince) });
      else out.push({ key: 'school', label: 'Another school' });
    } else if (a.school && a.school !== UNDECIDED_SCHOOL) {
      out.push({ key: 'school', label: (institutions.find((i) => i.id === a.school) || {}).name || a.school });
    }
    return out;
  }
  const describeAnswers = (a, institutions = []) => answerChips(a, institutions).map((c) => c.label);

  /** The follow-up answers a student gave about their status, as words (only for the groups they picked). */
  function statusAnswers(a) {
    const out = [];
    const word = (v) => (v === 'yes' ? 'Yes' : v === 'no' ? 'No' : '');
    const ids = a.identity || [];
    if (ids.includes('first_nations') && word(a.fnRegistered)) out.push({ label: 'Registered under the Indian Act', value: word(a.fnRegistered) });
    if (ids.includes('metis') && word(a.metisCitizen)) out.push({ label: 'Citizen of a Métis government', value: word(a.metisCitizen) });
    if (ids.includes('inuit') && word(a.inuitBeneficiary)) out.push({ label: 'Inuit land-claim beneficiary', value: word(a.inuitBeneficiary) });
    return out;
  }

  // ---- the quick filters are windows onto the same answers
  const communityValue = (a) => ((a.identity || []).length === 0 ? '' : a.identity.length === 1 ? a.identity[0] : 'multi');
  function withCommunity(a, value) {
    const next = cloneAnswers(a);
    if (value === 'multi') return next; // the "several communities" entry only displays the current answers
    return { ...next, identity: value ? [value] : [] };
  }

  /** '' = anywhere, 'school:<id>' = a listed school, 'prov:<code>' = a province or territory. */
  function locationValue(a) {
    if (a.school && a.school !== OTHER_SCHOOL && a.school !== UNDECIDED_SCHOOL) return 'school:' + a.school;
    if (a.school === OTHER_SCHOOL && a.otherSchoolProvince) return 'prov:' + a.otherSchoolProvince;
    return '';
  }
  function withLocation(a, value) {
    const next = { ...cloneAnswers(a), otherSchoolName: '' };
    if (!value) return { ...next, school: '', otherSchoolProvince: '' };
    const at = value.indexOf(':');
    const kind = value.slice(0, at);
    const rest = value.slice(at + 1);
    if (kind === 'prov') return { ...next, school: OTHER_SCHOOL, otherSchoolProvince: rest };
    if (kind === 'school') return { ...next, school: rest, otherSchoolProvince: '' };
    return next;
  }

  // ---- what the question screens edit
  /** Where will you study: 'bc' (optionally a school), 'elsewhere' (optionally a province), 'unsure', or '' (not asked yet). */
  function whereOf(a, institutions = []) {
    if (a.school && a.school !== OTHER_SCHOOL && a.school !== UNDECIDED_SCHOOL) {
      const school = institutions.find((i) => i.id === a.school);
      const away = school && school.province && school.province !== 'BC';
      return { where: away ? 'elsewhere' : 'bc', school: away ? '' : a.school, province: away ? school.province : '' };
    }
    if (a.school === OTHER_SCHOOL) {
      return a.otherSchoolProvince === 'BC'
        ? { where: 'bc', school: '', province: 'BC' }
        : { where: 'elsewhere', school: '', province: a.otherSchoolProvince || '' };
    }
    return { where: a.school === UNDECIDED_SCHOOL ? 'unsure' : '', school: '', province: '' };
  }
  function withWhere(a, { where, school = '', province = '' }) {
    const next = { ...cloneAnswers(a), school: '', otherSchoolName: '', otherSchoolProvince: '' };
    if (where === 'bc') return school ? { ...next, school } : { ...next, school: OTHER_SCHOOL, otherSchoolProvince: 'BC' };
    if (where === 'elsewhere') return { ...next, school: OTHER_SCHOOL, otherSchoolProvince: province };
    if (where === 'unsure') return { ...next, school: UNDECIDED_SCHOOL };
    return next;
  }

  const GOALS = [
    ['high_school', 'Finishing high school'], ['postsecondary', 'University or college'],
    ['training', 'Skills & training'], ['exploring', 'Still exploring'],
  ];
  const POSTSECONDARY_LEVELS = [
    ['college', 'College diploma or certificate'], ['undergraduate', 'Bachelor’s degree'],
    ['masters', 'Master’s degree'], ['doctoral', 'Doctoral degree'],
  ];
  /** One tap on a goal also settles the level where the goal names exactly one; a university or college student can add theirs. */
  function withGoal(a, goal, level = '') {
    const fixed = { high_school: 'high_school', training: 'trades_vocational' };
    return { ...cloneAnswers(a), goal, level: goal === 'postsecondary' ? level : (fixed[goal] || '') };
  }
  function planLabel(a) {
    if (a.level) return labelOf(LEVELS, a.level).replace(/: .*/, '');
    return a.goal ? labelOf(GOALS, a.goal) : '';
  }

  // ---------------------------------------------------------------- money, dates
  function formatMoney(value) {
    const n = Number(value);
    if (value === null || value === undefined || value === '' || !Number.isFinite(n)) return null;
    const cents = Math.abs(n % 1) > 0;
    return '$' + n.toLocaleString('en-CA', { minimumFractionDigits: cents ? 2 : 0, maximumFractionDigits: 2 });
  }

  /** The "price" of a scholarship: always what the provider LISTS, never a promise. `short` is the form used in large type. */
  function amountView(amount) {
    const none = { text: 'Amount not listed', short: 'Not listed', kind: 'unknown', value: null, note: 'not listed by the provider' };
    if (!amount) return none;
    const money = (v) => formatMoney(v);
    switch (amount.kind) {
      case 'fixed':
        return money(amount.fixed) ? { text: money(amount.fixed), short: money(amount.fixed), kind: 'fixed', value: Number(amount.fixed), note: 'listed value' } : none;
      case 'maximum':
        return money(amount.maximum)
          ? { text: 'Up to ' + money(amount.maximum), short: 'Up to ' + money(amount.maximum), kind: 'maximum', value: Number(amount.maximum), note: 'maximum, not guaranteed' } : none;
      case 'range':
        return money(amount.minimum) && money(amount.maximum)
          ? { text: money(amount.minimum) + '–' + money(amount.maximum), short: money(amount.minimum) + '–' + money(amount.maximum), kind: 'range', value: Number(amount.maximum), note: 'listed range' } : none;
      case 'pooled_total':
        return money(amount.pooled_total)
          ? { text: money(amount.pooled_total) + ' in total', short: money(amount.pooled_total) + ' in total', kind: 'pooled', value: Number(amount.pooled_total), note: 'shared between recipients' } : none;
      case 'variable':
        return { text: 'Varies', short: 'Varies', kind: 'variable', value: null, note: 'depends on the applicant' };
      default:
        return none;
    }
  }

  /** When the amount is not a single figure the provider's own words are often the useful part. */
  function amountWords(amount) {
    if (!amount || !amount.raw_text) return '';
    if (['fixed', 'maximum', 'range', 'pooled_total'].includes(amount.kind)) return '';
    return clamp(String(amount.raw_text).replace(/\s+/g, ' ').trim(), 320);
  }

  function plainDate(iso) {
    const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso || '');
    return m ? `${MONTHS[Number(m[2]) - 1]} ${Number(m[3])}, ${m[1]}` : null;
  }
  function isoDate(date) {
    return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
  }
  function daysBetween(fromIso, toIso) {
    const part = (s) => { const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(s); return Date.UTC(Number(m[1]), Number(m[2]) - 1, Number(m[3])); };
    return Math.round((part(toIso) - part(fromIso)) / 86400000);
  }
  function nextOccurrence(rules, todayIso) {
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
  function urgencyText(days) {
    if (days === null || days === undefined || days < 0) return null;
    return days === 0 ? 'Closes today' : days === 1 ? 'Closes tomorrow' : `Closes in ${days} days`;
  }

  /** What to tell a student about timing. Dates are shown as written by the provider; time zones are never guessed. */
  function deadlineView(deadlines, todayIso) {
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
  const availabilityView = (status) => { const [label, tone] = AVAILABILITY[status] || AVAILABILITY.unknown; return { label, tone }; };

  function ruleCounts(row) {
    const unknown = row.unknown || [];
    const needAnswer = unknown.filter((r) => r.unknown_reason === 'profile_missing').length;
    return { passed: (row.passed || []).length, failed: (row.failed || []).length, needAnswer, confirm: unknown.length - needAnswer };
  }

  /** One honest sentence about eligibility. A rule nobody can check from a profile is "ask the provider", not "no". */
  function fitView(row) {
    const c = row.counts;
    if (row.status === 'not_eligible' || c.failed > 0) return { key: 'no', label: 'Probably not eligible', tone: 'muted', rank: 4 };
    if (row.status === 'potential_fit') return { key: 'fit', label: 'Looks like a fit', tone: 'good', rank: 0 };
    if (c.needAnswer > 0) return { key: 'more', label: 'More answers would help', tone: 'info', rank: 2 };
    if (c.passed > 0) return { key: 'meets', label: 'Meets what we can check', tone: 'good', rank: 1 };
    return { key: 'ask', label: 'Ask the provider about eligibility', tone: 'neutral', rank: 3 };
  }

  function sourceView(row) {
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

  const typeLabel = (row) => (row.type === 'funding_channel' ? 'Funding program' : 'Scholarship & award');

  // ---------------------------------------------------------------- small facts for cards and the detail view
  const BADGE_STOP = new Set(['of', 'and', 'the', 'for', 'in', 'on', 'at', 'by', 'de', 'la', 'le', 'inc', 'ltd', 'corp', 'co', 'estate']);
  function hashOf(text) {
    let h = 0;
    for (const ch of String(text)) h = (h * 31 + ch.codePointAt(0)) >>> 0;
    return h;
  }
  /** Two to four letters for a provider's badge, and one of three soft tones (the same provider always gets the same one). */
  function providerBadge(name) {
    const clean = String(name || '').replace(/^the\s+/i, '').trim();
    const inParens = /\(([A-Z]{2,6})\)/.exec(clean);
    let text = '';
    if (inParens) {
      text = inParens[1];
    } else {
      const head = clean.split(/,|\s+and\s+|\s+&\s+|\s+–\s+/i)[0];
      const words = head.split(/[\s\-–/]+/).filter(Boolean);
      const first = words.length ? words[0].replace(/\./g, '') : '';
      if (/^[A-Z]{2,5}$/.test(first)) {
        text = first;
      } else {
        text = words.filter((w) => !BADGE_STOP.has(fold(w).replace(/\./g, '')))
          .map((w) => fold(w).replace(/[^a-z]/g, '')[0] || '').join('').toUpperCase().slice(0, 4);
      }
    }
    if (text.length < 2) text = fold(clean).replace(/[^a-z]/g, '').slice(0, 3).toUpperCase() || '·';
    return { text, tone: ['peach', 'sage', 'blue'][hashOf(clean) % 3] };
  }

  const allRules = (row) => [...(row.passed || []), ...(row.failed || []), ...(row.unknown || [])];
  const IDENTITY_WORDS = [['First Nations', /first nations?/i], ['Inuit', /inuit/i], ['Métis', /m[ée]tis/i]];

  /** Who the provider names, read from the identity rule the service already extracted ([] when the page names no community). */
  function communitiesOf(row) {
    let allowed = null;
    for (const r of allRules(row)) {
      if (!r || r.field !== 'indigenous_identity') continue;
      const named = IDENTITY_WORDS.filter(([, re]) => re.test(String(r.rule || ''))).map(([label]) => label);
      if (!named.length) continue;
      allowed = allowed === null ? named : allowed.filter((l) => named.includes(l));
    }
    return allowed || [];
  }

  const provinceCodesIn = (text) => (String(text || '').match(/\b[A-Z]{2}\b/g) || []).filter((c) => PROVINCES.some(([k]) => k === c));

  /** Where the provider says the student must study or live, in words ([] when no such rule was found). */
  function placeFacts(row, institutions = []) {
    const out = [];
    for (const r of allRules(row)) {
      if (!r) continue;
      if (r.field === 'institution_id') {
        const m = /^Institution is (?:one of )?(.+)$/.exec(String(r.rule || ''));
        if (!m) continue;
        const names = m[1].split(/,\s*|\s+or\s+/).map((id) => (institutions.find((i) => i.id === id.trim()) || {}).name || id.trim());
        out.push(names.length > 2 ? `Students at ${names.length} schools` : 'Students at ' + names.join(' or '));
      } else if (r.field === 'institution_province' || r.field === 'residence_province') {
        const names = provinceCodesIn(r.rule).map(provinceName);
        if (!names.length) continue;
        const where = names.length > 2 ? `${names.length} provinces or territories` : names.join(' or ');
        out.push((r.field === 'residence_province' ? 'Lives in ' : 'Studying in ') + where);
      }
    }
    return [...new Set(out)];
  }
  const placeOf = (row, institutions) => placeFacts(row, institutions).join(' · ');

  const LEVEL_NAMES = {
    high_school: 'High school', trades_vocational: 'Trades or vocational training', college: 'College',
    undergraduate: 'Bachelor’s degree', masters: 'Master’s degree', doctoral: 'Doctoral degree',
  };
  /** The levels of study the provider names, read from the level rule the service extracted ([] when the page names none). */
  function levelsOf(row) {
    let allowed = null;
    for (const r of allRules(row)) {
      if (!r || r.field !== 'education_level') continue;
      const m = /^Education level is (?:one of )?(.+)$/.exec(String(r.rule || ''));
      if (!m) continue;
      const named = m[1].split(/,\s*/).map((k) => LEVEL_NAMES[k.trim()]).filter(Boolean);
      if (!named.length) continue;
      allowed = allowed === null ? named : allowed.filter((l) => named.includes(l));
    }
    return allowed || [];
  }
  /** "Study plans": the levels, plus full-time or part-time when the provider asks for one. */
  function plansOf(row) {
    const out = [...levelsOf(row)];
    for (const r of allRules(row)) {
      const m = r && r.field === 'study_status' ? /^Study status is (full-time|part-time)/i.exec(String(r.rule || '')) : null;
      if (m) out.push(cap(m[1].toLowerCase()));
    }
    return [...new Set(out)];
  }

  /** A large figure with its qualifier in small type. "Up to" and "in total" move into the qualifier; they are never dropped. */
  function amountParts(view) {
    switch (view.kind) {
      case 'maximum': return { figure: view.short.replace(/^Up to /, ''), note: 'Up to · ' + view.note };
      case 'pooled': return { figure: view.short.replace(/ in total$/, ''), note: 'In total · ' + view.note };
      case 'unknown': return { figure: view.short, note: 'Ask the provider' };
      default: return { figure: view.short, note: cap(view.note) };
    }
  }

  // ---------------------------------------------------------------- joining the two API answers
  function buildRow(listItem, match) {
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
    row.badge = providerBadge(row.provider);
    row.communities = communitiesOf(row);
    return row;
  }
  function joinRows(listItems, matchItems) {
    const byId = new Map((matchItems || []).map((m) => [m.opportunity_id, m]));
    return listItems.map((l) => buildRow(l, byId.get(l.id)));
  }
  /** Cards and the "deadline" sort need the dated view once; keep it on the row. */
  function withDeadlines(rows, todayIso) {
    for (const r of rows) { r.deadline = deadlineView(r.deadlines, todayIso); r.deadlineSort = r.deadline.sortKey; }
    return rows;
  }
  const lastCheckedOf = (rows) => rows.map((r) => r.lastVerified).filter(Boolean).sort().pop() || '';
  function dataTag(mode, lastChecked) {
    if (mode === 'demo') return 'Demo · Made-up data';
    const when = plainDate(lastChecked);
    return when ? `Checked ${when}` : 'Official sources';
  }

  // ---------------------------------------------------------------- filters and sorting
  const defaultFilters = () => ({ q: '', fit: new Set(), type: new Set(), source: new Set(), avail: new Set(), amount: 'any', showNo: false });

  const AMOUNT_TESTS = {
    any: () => true,
    listed: (v) => v !== null,
    lt1000: (v) => v !== null && v < 1000,
    mid: (v) => v !== null && v >= 1000 && v <= 5000,
    gt5000: (v) => v !== null && v > 5000,
    unknown: (v) => v === null,
  };
  const AMOUNT_BUCKETS = [
    ['any', 'Any amount'], ['listed', 'Amount is listed'], ['lt1000', 'Under $1,000'], ['mid', '$1,000 to $5,000'],
    ['gt5000', 'Over $5,000'], ['unknown', 'Amount not listed'],
  ];

  function matchesQuery(row, q) {
    const terms = fold(q).split(/\s+/).filter(Boolean);
    if (!terms.length) return true;
    const hay = fold([row.title, row.provider, row.donor, row.summary].join(' '));
    return terms.every((t) => hay.includes(t));
  }

  function applyFilters(rows, f, personalized) {
    return rows.filter((r) =>
      matchesQuery(r, f.q)
      && (f.type.size === 0 || f.type.has(r.type))
      && (f.source.size === 0 || f.source.has(r.source_kind))
      && (f.avail.size === 0 || f.avail.has(r.availability))
      && (f.fit.size === 0 || f.fit.has(r.fit.key))
      && (AMOUNT_TESTS[f.amount] || AMOUNT_TESTS.any)(r.amountView.value)
      && (f.showNo || !personalized || r.fit.key !== 'no'));
  }

  const SORTS = [['best', 'Best match'], ['deadline', 'Deadline: soonest'], ['amount', 'Amount: high to low'], ['name', 'Name: A to Z']];
  const AVAIL_RANK = { open: 0, upcoming: 1, contact_administrator: 2, unknown: 3, closed: 4 };

  function sortRows(rows, how, personalized) {
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

  // ---------------------------------------------------------------- texts for cards and the detail view
  /** Directory entries repeat a long boilerplate sentence; a card only needs what is specific to the award. */
  function cardSummary(row) {
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
    annual_rule_unconfirmed: 'The provider lists a yearly date. Check their page to confirm the date for this year.',
    closing_time_ambiguous: 'The provider does not say exactly when the last day ends.',
    eligibility_not_fully_structured: 'Some conditions are written in the provider’s own words, so we cannot check all of them for you.',
    verification_stale: 'This was last checked a while ago, so the provider may have changed it since.',
    never_verified: 'We have not checked this against the provider’s page yet.',
    source_changed_since_verification: 'The provider’s page has changed since we last checked it.',
    historical_cycle_only: 'Only a past application round is listed.',
    stale: 'This information has not been re-checked recently.',
    source_modified_old: 'The page this comes from has not been updated for a long time.',
  };
  /** These flags only repeat what the amount and the deadline already say on screen. */
  const QUIET_FLAGS = new Set(['amount_unknown', 'deadline_unknown', 'local_administrator_deadline']);
  const flagText = (flag) => FLAGS[flag] || cap(String(flag).replace(/_/g, ' ')) + '.';
  const visibleFlags = (flags) => (flags || []).filter((f) => !QUIET_FLAGS.has(f));

  function evidenceLabel(path = '') {
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
  function evidenceList(row, detail) {
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
  function providerStatements(detail) {
    const cycle = ((detail && detail.cycles) || [])[0];
    return ((cycle && cycle.eligibility && cycle.eligibility.unstructured) || []).map((u) => u.text).filter(Boolean);
  }

  /** A row built from the detail endpoint alone (a link opened directly to something the list does not show). */
  function rowFromDetail(detail, todayIso) {
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
  function prettyRule(rule, institutions = []) {
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

  const RULE_LABELS = {
    indigenous_identity: 'Community', first_nations_registered: 'Indian Act registration', metis_citizen: 'Métis citizenship',
    inuit_beneficiary: 'Inuit land-claim beneficiary', residence_province: 'Where you live', institution_id: 'School',
    institution_province: 'Where you study', education_level: 'Level of study', study_status: 'Full-time or part-time',
  };
  const ruleLabel = (rule) => RULE_LABELS[rule && rule.field] || 'From the provider';
  const sameText = (s) => String(s || '').replace(/\s+/g, ' ').trim().toLowerCase();

  /** With answers: every rule, marked as matching, not matching, or needing someone to confirm. */
  function ruleItems(row, institutions = []) {
    const make = (kind, why) => (r) => ({ kind, label: ruleLabel(r), text: cap(prettyRule(r, institutions)), why: why(r) });
    return [
      ...(row.passed || []).map(make('pass', () => 'This matches your answers.')),
      ...(row.failed || []).map(make('fail', () => 'This does not match your answers.')),
      ...(row.unknown || []).map(make('unknown', (r) => (r.unknown_reason === 'profile_missing' ? 'We need an answer from you to check this.' : 'Only the provider can confirm this.'))),
    ];
  }

  /** Without answers: what the provider asks for. The provider's own sentences are shown elsewhere, so they are not listed twice. */
  function requirementList(row, detail, institutions = []) {
    const said = new Set(providerStatements(detail).map(sameText));
    return allRules(row).filter((r) => !said.has(sameText(r.rule)))
      .map((r) => ({ kind: 'ask', label: ruleLabel(r), text: cap(prettyRule(r, institutions)), why: '' }));
  }

  // ---------------------------------------------------------------- what the Government of Canada's reproduction terms ask us to say
  /** Non-commercial reproduction is allowed if the copy says it is a copy of an official work and is not endorsed by the Government. */
  function governmentAttribution(row, quotes) {
    const fromCanada = (quotes || []).some((q) => /^https?:\/\/(www\.)?sac-isc\.gc\.ca\//.test(q.url || ''));
    if (!fromCanada) return null;
    const material = row.source_kind === 'directory_listing' ? 'Indigenous Bursaries Search Tool' : row.title;
    return `Contains information from “${material}”, published by Indigenous Services Canada. This is a copy of an official work published by the Government of Canada; it was not produced in affiliation with, or with the endorsement of, the Government of Canada.`;
  }

  // ---------------------------------------------------------------- the detail view's illustration and next steps
  /** One of the three paper illustrations, matched to the kind of support. */
  function artFor(row) {
    if (row.type === 'funding_channel') return { asset: 'paper-portfolio', tone: 'blue' };
    if (/\b(skills?|trades?|training|apprentice\w*)\b/i.test(row.title || '')) return { asset: 'skills-path', tone: 'sage' };
    return { asset: 'study-kit', tone: 'peach' };
  }

  /** The service writes its advice with raw addresses in it; a student reads "the provider's page". */
  function plainAction(text) {
    return String(text || '')
      .replace(/:\s*https?:\/\/\S+$/i, '')
      .replace(/https?:\/\/\S+?(?=[.,;]?(?:\s|$))/gi, 'the provider’s page')
      .replace(/\s+/g, ' ').trim()
      .replace(/([^.!?])$/, '$1.');
  }

  function nextSteps(row, detail) {
    const route = row.route || {};
    const how = String(route.instructions || '').trim();
    const steps = [{ title: 'Read the provider’s page', text: 'Start with their current details, dates and conditions.', url: row.officialUrl }];
    if (route.route_type === 'contact_administrator') {
      steps.push({ title: 'Contact the administrator', text: how || 'The deadline is set locally. Ask how and when to apply.', url: route.contact_url || route.url || row.officialUrl });
    } else if (route.route_type === 'online_application') {
      steps.push({ title: 'Apply with the provider', text: how || 'Use the application on the provider’s page.', url: route.url || row.officialUrl });
    } else if (route.route_type === 'institution_portal') {
      steps.push({ title: 'Apply through the school', text: how || 'This award is applied for through the school’s own award application.', url: route.url || '' });
    } else if (how) {
      steps.push({ title: 'How to apply', text: how, url: route.url || '' });
    } else {
      steps.push({ title: 'Ask how to apply', text: 'The provider’s page does not give a clear way to apply. Contact them to ask.', url: route.contact_url || '' });
    }
    const docs = (((detail && detail.opportunity) || {}).required_documents || []).map((d) => d.label || d.type).filter(Boolean);
    if (docs.length) steps.push({ title: 'Prepare your documents', text: docs.join(', ') + '.' });
    const siblings = (detail && detail.shared_application_with) || [];
    if (siblings.length) {
      steps.push({ title: 'One application, several awards', text: `The same form covers ${siblings.length} other award${siblings.length === 1 ? '' : 's'}. Each has its own conditions, so read them.` });
    }
    steps.push({ title: 'Confirm before you apply', text: plainAction(row.nextAction) || 'Check eligibility, documents and dates with the provider.' });
    return steps;
  }

  // ---------------------------------------------------------------- routes
  /** '#explore' -> {view:'explore'}; '#program/<id>' -> {view:'program', id}. The app decides what an unknown view means. */
  function parseRoute(hash) {
    const raw = String(hash || '').replace(/^#\/?/, '');
    if (raw.startsWith('program/')) {
      let id = raw.slice(8);
      try { id = decodeURIComponent(id); } catch { /* an address typed by hand: use it as written */ }
      return id ? { view: 'program', id } : { view: 'explore' };
    }
    return { view: raw };
  }
  const programHash = (id) => '#program/' + encodeURIComponent(id);

  return {
    PROVINCES, LEVELS, IDENTITIES, GOALS, POSTSECONDARY_LEVELS, OTHER_SCHOOL, UNDECIDED_SCHOOL, AMOUNT_BUCKETS, SORTS,
    provinceName, levelName, fold, cap, clamp, escapeHTML, safeUrl, hostOf,
    blankAnswers, cloneAnswers, buildProfile, isPersonalized, answerChips, describeAnswers, statusAnswers, planLabel,
    communityValue, withCommunity, locationValue, withLocation, whereOf, withWhere, withGoal,
    formatMoney, amountView, amountWords, plainDate, isoDate, daysBetween, nextOccurrence, urgencyText, deadlineView,
    availabilityView, ruleCounts, fitView, sourceView, typeLabel, providerBadge, communitiesOf, placeFacts, placeOf, levelsOf, plansOf, amountParts,
    buildRow, joinRows, withDeadlines, lastCheckedOf, dataTag,
    defaultFilters, matchesQuery, applyFilters, sortRows,
    cardSummary, flagText, visibleFlags, evidenceLabel, evidenceList, providerStatements, rowFromDetail,
    prettyRule, ruleLabel, ruleItems, requirementList, governmentAttribution, artFor, plainAction, nextSteps,
    parseRoute, programHash,
  };
});
