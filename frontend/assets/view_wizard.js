// The questionnaire: five short questions, every one optional. "Not sure" and a skipped question both mean "unknown" - never "no".
import { h, icon } from './dom.js';
import { IDENTITIES, LEVELS, OTHER_SCHOOL, PROVINCES, UNDECIDED_SCHOOL } from './logic.js';

export const visibleSteps = (a) => [1, ...(a.identity.length ? [2] : []), 3, 4, 5];

const choice = ({ type, name, value, checked, text, hint, onChange }) =>
  h('label', { class: 'choice' },
    h('input', { type, name, value, checked, onChange }),
    h('span', {}, h('span', { class: 'choice__text' }, text), hint ? h('span', { class: 'choice__hint' }, hint) : null));

const fieldset = (question, helpText, ...body) =>
  h('fieldset', {}, h('legend', { id: 'page-title', tabindex: '-1' }, question), helpText ? h('p', { class: 'wizard__help' }, helpText) : null, ...body);

function stepIdentity(a) {
  return fieldset('Which of these describe you?',
    'Choose all that apply. Many awards are for one group in particular. You can skip this if you would rather not say.',
    h('div', { class: 'choices' }, IDENTITIES.map(([key, label]) => choice({
      type: 'checkbox', name: 'identity', value: key, checked: a.identity.includes(key), text: label,
      onChange: (e) => { const i = a.identity.indexOf(key); if (e.target.checked && i < 0) a.identity.push(key); if (!e.target.checked && i >= 0) a.identity.splice(i, 1); },
    }))));
}

function stepStatus(a) {
  const groups = [];
  if (a.identity.includes('first_nations')) groups.push(['fnRegistered', 'Are you registered under the Indian Act (do you have Indian status)?']);
  if (a.identity.includes('metis')) groups.push(['metisCitizen', 'Are you a citizen of a Métis government, such as Métis Nation British Columbia?']);
  if (a.identity.includes('inuit')) groups.push(['inuitBeneficiary', 'Are you a beneficiary of an Inuit land-claims agreement?']);
  return fieldset('A little more about your status',
    'Some funding is only for registered First Nations people, Métis citizens or Inuit beneficiaries. We never ask for card numbers, proof or documents.',
    groups.map(([key, title]) => h('div', { class: 'wizard__group', role: 'radiogroup', 'aria-labelledby': `q-${key}` },
      h('h3', { id: `q-${key}` }, title),
      h('div', { class: 'choices choices--two' }, [['yes', 'Yes'], ['no', 'No'], ['', 'Not sure, or prefer not to say']].map(([value, text]) => choice({
        type: 'radio', name: key, value, checked: (a[key] || '') === value, text, onChange: () => { a[key] = value; },
      }))))));
}

function stepResidence(a) {
  const select = h('select', { class: 'select', id: 'province', value: a.province, onChange: (e) => { a.province = e.target.value; } },
    h('option', { value: '' }, 'Choose a province or territory'), PROVINCES.map(([code, name]) => h('option', { value: code }, name)));
  return fieldset('Where do you live right now?', 'Some funding is only for people who live in a particular province or territory.',
    h('div', { class: 'field' }, h('label', { class: 'field__label', for: 'province' }, 'Province or territory'), select));
}

function stepStudy(a) {
  return fieldset('What are you studying, or planning to study?', 'Pick the closest match. Funding is often tied to a level of study.',
    h('div', { class: 'choices' }, LEVELS.map(([value, text, hint]) => choice({
      type: 'radio', name: 'level', value, checked: a.level === value, text, hint, onChange: () => { a.level = value; },
    }))),
    h('div', { class: 'wizard__group', role: 'radiogroup', 'aria-labelledby': 'q-status' },
      h('h3', { id: 'q-status' }, 'Full-time or part-time?'),
      h('div', { class: 'choices choices--two' }, [['full_time', 'Full-time'], ['part_time', 'Part-time']].map(([value, text]) => choice({
        type: 'radio', name: 'studyStatus', value, checked: a.studyStatus === value, text, onChange: () => { a.studyStatus = value; },
      })))));
}

function stepSchool(a, institutions) {
  const extra = h('div', {});
  const paintExtra = () => extra.replaceChildren(...(a.school !== OTHER_SCHOOL ? [] : [
    h('div', { class: 'field' }, h('label', { class: 'field__label', for: 'other-name' }, 'Name of the school (optional)'),
      h('input', { class: 'input', id: 'other-name', type: 'text', maxlength: '200', value: a.otherSchoolName, autocomplete: 'off', onInput: (e) => { a.otherSchoolName = e.target.value; } })),
    h('div', { class: 'field' }, h('label', { class: 'field__label', for: 'other-prov' }, 'Where is it?'),
      h('select', { class: 'select', id: 'other-prov', value: a.otherSchoolProvince, onChange: (e) => { a.otherSchoolProvince = e.target.value; } },
        h('option', { value: '' }, 'Choose a province or territory'), PROVINCES.map(([code, name]) => h('option', { value: code }, name)))),
  ]));
  const inBC = institutions.filter((i) => i.province === 'BC');
  const select = h('select', { class: 'select', id: 'school', value: a.school, onChange: (e) => { a.school = e.target.value; paintExtra(); } },
    h('option', { value: '' }, 'Choose a school'),
    inBC.length ? h('optgroup', { label: 'In British Columbia' }, inBC.map((i) => h('option', { value: i.id }, i.name))) : null,
    h('optgroup', { label: 'Somewhere else' },
      h('option', { value: OTHER_SCHOOL }, 'A school in another province or territory'),
      h('option', { value: UNDECIDED_SCHOOL }, 'I have not decided yet')));
  paintExtra();
  return fieldset('Which school do you attend, or hope to attend?', 'Some awards are only for students at one school. Pick the closest match.',
    h('div', { class: 'field' }, h('label', { class: 'field__label', for: 'school' }, 'School'), select), extra);
}

const hasAnswer = {
  1: (a) => a.identity.length > 0,
  2: (a) => Boolean(a.fnRegistered || a.metisCitizen || a.inuitBeneficiary),
  3: (a) => Boolean(a.province),
  4: (a) => Boolean(a.level || a.studyStatus),
  5: (a) => Boolean(a.school),
};

export function wizardView(ctx, requested) {
  const a = ctx.state.answers;
  const order = visibleSteps(a);
  const step = order.includes(requested) ? requested : order.find((s) => s > requested) || order[order.length - 1];
  const position = order.indexOf(step);
  const last = position === order.length - 1;
  const body = { 1: () => stepIdentity(a), 2: () => stepStatus(a), 3: () => stepResidence(a), 4: () => stepStudy(a), 5: () => stepSchool(a, ctx.state.institutions) }[step]();

  const label = () => (last ? 'Show my scholarships' : hasAnswer[step](a) ? 'Next' : 'Skip');
  const next = h('button', { class: 'btn btn--primary', type: 'button', onClick: () => {
    const now = visibleSteps(a);
    const after = now[now.indexOf(step) + 1];
    if (after === undefined) ctx.finishWizard(); else ctx.nav(`#/start/${after}`);
  } }, label());
  body.addEventListener('change', () => { next.textContent = label(); });
  const back = h('button', { class: 'btn btn--ghost', type: 'button', onClick: () => {
    const before = visibleSteps(a)[visibleSteps(a).indexOf(step) - 1];
    ctx.nav(before === undefined ? '#/' : `#/start/${before}`);
  } }, icon('back', 18), 'Back');

  const bar = h('div', { class: 'progress__bar' });
  bar.style.setProperty('--p', `${((position + 1) / order.length) * 100}%`);
  return h('div', { class: 'page' }, h('div', { class: 'container wizard' }, h('div', { class: 'wizard__card' },
    h('div', { class: 'progress' },
      h('div', { class: 'progress__text' }, h('span', {}, `Question ${position + 1} of ${order.length}`), h('span', {}, 'Every question is optional')),
      h('div', { class: 'progress__track', role: 'presentation' }, bar)),
    body,
    h('div', { class: 'wizard__actions' }, back, h('span', { class: 'spacer' }), next),
    h('p', { class: 'privacy-note' }, icon('lock', 18), h('span', {}, 'Your answers stay in this browser tab. They are used once to sort the list, and they are not saved or shared.')))));
}
