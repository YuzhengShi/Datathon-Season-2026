// Parts shared by every page: the top bar, the footer and the small widgets that carry meaning (badges, price, deadline).
import { CONTACT_EMAIL, SITE_NAME } from './config.js';
import { h, icon } from './dom.js';
import { availabilityView, plainDate, sourceView, urgencyText } from './logic.js';

export const listLabel = (n) => (n ? `My list, ${n} saved` : 'My list');

export function header(ctx, { search = false } = {}) {
  const count = h('span', { class: 'count js-list-count', hidden: ctx.savedCount() === 0 }, String(ctx.savedCount()));
  return h('header', { class: 'topbar' }, h('div', { class: 'container topbar__inner' },
    h('a', { class: 'brand', href: '#/' },
      h('span', { class: 'brand__mark' }, icon('compass', 24)),
      h('span', {}, h('span', { class: 'brand__name' }, SITE_NAME), h('span', { class: 'brand__tag' }, 'for First Nations, Inuit and Métis students'))),
    search ? searchForm(ctx) : null,
    h('nav', { class: 'topbar__nav', 'aria-label': 'Main' },
      h('button', { class: 'btn btn--ghost btn--small js-list-button', type: 'button', 'aria-label': listLabel(ctx.savedCount()), onClick: () => ctx.openList() },
        icon('bookmark', 18), h('span', { class: 'label' }, 'My list'), count),
      h('a', { class: 'btn btn--ghost btn--small', href: '#/about' }, 'About'))));
}

function searchForm(ctx) {
  const input = h('input', { class: 'search__input', type: 'search', name: 'q', value: ctx.state.filters.q, autocomplete: 'off',
    placeholder: 'Search scholarships', 'aria-label': 'Search scholarships', onInput: (e) => ctx.onSearch(e.target.value) });
  return h('form', { class: 'search', role: 'search', onSubmit: (e) => { e.preventDefault(); ctx.onSearch(input.value); } },
    input, h('button', { class: 'search__btn', type: 'submit', 'aria-label': 'Search' }, icon('search', 22)));
}

export function footer(ctx) {
  const checked = ctx.state.lastChecked ? ` Information last checked ${plainDate(ctx.state.lastChecked)}.` : '';
  return h('footer', { class: 'footer' }, h('div', { class: 'container footer__grid' },
    h('div', {},
      h('p', {}, h('strong', {}, 'Free and non-commercial. '), 'Funding Navigator helps students find money for school. It takes no applications and charges no one.'),
      h('p', {}, 'Funding details change. Always confirm with the provider before you apply.' + checked)),
    h('div', {},
      h('p', {}, icon('lock', 15), ' Your answers stay in this browser tab. They are not saved, and they never appear in the address bar.'),
      h('p', {}, h('a', { href: '#/about' }, 'How this works'), CONTACT_EMAIL ? [' · ', h('a', { href: 'mailto:' + CONTACT_EMAIL }, 'Send a correction')] : null))));
}

export function badge(tone, text, iconName) {
  return h('span', { class: `badge badge--${tone}` }, iconName ? icon(iconName, 14) : null, text);
}
const THUMBS = { school: 'school', community: 'heart', business: 'briefcase', program: 'landmark', award: 'star' };
export const thumb = (category) => h('div', { class: `card__thumb thumb--${category}`, 'aria-hidden': 'true' }, icon(THUMBS[category] || 'star', 30));

export function fitBadge(row) {
  const f = row.fit;
  const map = { good: ['good', 'check'], info: ['info', 'help'], neutral: ['outline', 'help'], muted: ['muted', 'x'] };
  const [tone, glyph] = map[f.tone] || map.neutral;
  return badge(tone, f.label, glyph);
}
export function sourceBadge(row) {
  const s = sourceView(row);
  return s.tone === 'warn' ? badge('warn', s.year ? `${s.label} · ${s.year}` : s.label, 'info') : badge('good', s.label, 'shield');
}
export function availabilityBadge(row) {
  if (!['open', 'upcoming', 'closed'].includes(row.availability)) return null;
  const v = availabilityView(row.availability);
  return badge(v.tone === 'good' ? 'good' : v.tone === 'info' ? 'info' : 'muted', v.label, 'clock');
}

export function priceBlock(row) {
  const a = row.amountView;
  return h('div', { class: a.kind === 'unknown' ? 'price price--none' : 'price' }, a.text, a.note ? h('span', { class: 'price__note' }, a.note) : null);
}
export function deadlineBlock(row) {
  const d = row.deadline;
  const urgent = d.soon ? urgencyText(d.days) : null;
  return h('div', { class: d.soon ? 'deadline deadline--soon' : 'deadline' },
    icon('calendar', 15), ' ', d.text,
    urgent ? h('span', { class: 'deadline__more' }, urgent) : (d.detail ? h('span', { class: 'deadline__more' }, d.detail) : null));
}

export function saveButton(row, ctx, { block = false } = {}) {
  const button = h('button', { type: 'button' });
  const paint = () => {
    const on = ctx.isSaved(row.id);
    button.className = `btn btn--small ${on ? 'btn--saved' : 'btn--secondary'}${block ? ' btn--block' : ''}`;
    button.setAttribute('aria-pressed', String(on));
    button.replaceChildren(icon(on ? 'check' : 'bookmark', 16), on ? 'Saved to my list' : 'Save to my list');
  };
  button.addEventListener('click', () => { ctx.toggleSave(row); paint(); });
  paint();
  return button;
}

export const banner = (tone, iconName, ...children) => h('div', { class: `banner${tone === 'warn' ? ' banner--warn' : ''}`, role: 'note' }, icon(iconName, 20), h('div', {}, ...children));