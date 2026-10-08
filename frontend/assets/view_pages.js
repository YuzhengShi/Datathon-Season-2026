// The welcome page, the About page and the small states (loading, error, not found).
import { CONTACT_EMAIL } from './config.js';
import { h, icon } from './dom.js';
import { badge } from './views_common.js';

function previewCard(title, tone, label, price) {
  return h('div', { class: 'preview__card' },
    h('strong', {}, title), h('div', { class: 'badges', style: null }, badge(tone, label, tone === 'good' ? 'shield' : 'info')),
    h('div', { class: 'preview__line' }), h('div', { class: 'preview__line preview__line--short' }), h('strong', {}, price));
}

export function welcomeView() {
  return h('div', { class: 'page' }, h('div', { class: 'container' },
    h('section', { class: 'hero' },
      h('div', {},
        h('h1', { id: 'page-title', tabindex: '-1' }, 'Find scholarships and funding you may qualify for'),
        h('p', { class: 'hero__lede' }, 'A free guide for First Nations, Inuit and Métis students in Canada. Answer a few quick questions and see funding that fits, with an honest note about anything we could not confirm.'),
        h('div', { class: 'hero__actions' },
          h('a', { class: 'btn btn--primary', href: '#/start/1' }, 'Start: about one minute'),
          h('a', { class: 'btn btn--secondary', href: '#/results?browse=1' }, 'Browse everything')),
        h('p', { class: 'small muted' }, 'Rather not answer yet? ', h('a', { href: '#/results?sample=1' }, 'See an example'), ' with made-up answers.')),
      h('div', { class: 'preview', 'aria-hidden': 'true' },
        previewCard('A scholarship at your school', 'good', 'Checked on the provider’s page', 'Up to $5,000'),
        previewCard('A national award', 'warn', 'Government directory entry', '$1,000'),
        previewCard('A funding program', 'good', 'Official program page', 'Amount not listed'))),
    h('section', { class: 'pillars', 'aria-label': 'What to expect' },
      h('div', { class: 'pillar' }, h('h3', {}, icon('lock', 20), 'Your answers stay with you'), h('p', {}, 'We never ask for your name, status number or any documents. Answers are used to sort this page and nothing is saved.')),
      h('div', { class: 'pillar' }, h('h3', {}, icon('shield', 20), 'We show where it comes from'), h('p', {}, 'Every card says whether we read it on the provider’s own page or found it in a government directory that may be out of date.')),
      h('div', { class: 'pillar' }, h('h3', {}, icon('hand', 20), 'Free, no sales pitch'), h('p', {}, 'No ads, no sign-up, no fees. You always apply directly with the provider.'))),
    h('section', { 'aria-labelledby': 'how' },
      h('h2', { id: 'how', style: null }, 'How it works'),
      h('ol', { class: 'how' },
        h('li', {}, h('strong', {}, 'Answer a few questions.'), ' Every one can be skipped.'),
        h('li', {}, h('strong', {}, 'Browse what fits.'), ' Search, filter and sort like any store, and save favourites to your list.'),
        h('li', {}, h('strong', {}, 'Apply with the provider.'), ' We link you to the provider’s page and tell you what to confirm.')))));
}

const section = (title, ...body) => h('section', { class: 'panel' }, h('h2', {}, title), ...body);

export function aboutView() {
  return h('div', { class: 'page' }, h('div', { class: 'container', style: null },
    h('h1', { id: 'page-title', tabindex: '-1' }, 'About Funding Navigator'),
    section('What this is',
      h('p', {}, 'A free, non-commercial guide that collects scholarships, bursaries and funding programs for First Nations, Inuit and Métis students, so you do not have to hunt through dozens of websites. It does not take applications and it does not choose winners.')),
    section('How matching works',
      h('p', {}, 'We compare your answers with the conditions each provider has published. A card can say that you meet the requirements we are able to check, that something needs the provider’s confirmation, or that you probably do not qualify.'),
      h('p', {}, 'It is never a prediction that you will receive funding. Many requirements, such as good academic standing or community involvement, can only be judged by the provider, so we say so instead of guessing.')),
    section('Where the information comes from',
      h('p', {}, h('strong', {}, 'Checked on the provider’s page: '), 'a computer read the provider’s own web page and every detail we show is backed by a quote from it.'),
      h('p', {}, h('strong', {}, 'Government directory entry: '), 'listed in a federal directory of Indigenous bursaries. Those entries can be many years old and have no deadline, so treat them as a lead and confirm with the provider.'),
      h('p', {}, 'We show the date we last checked each page. “Checked” here means a computer verified the quotes; a person has not yet reviewed it. Always confirm on the provider’s page before you apply.')),
    section('Sources and permissions',
      h('p', {}, 'Facts, amounts and dates come from the public web pages of the organisations that offer the funding. We show short quotations with a link back to the page and the date we last checked it, and we honour each site’s robots.txt. Nothing is copied wholesale.'),
      h('p', {}, 'Information from Indigenous Services Canada (the Indigenous Bursaries Search Tool and its program pages) is reproduced under the Government of Canada’s non-commercial reproduction terms. Those copies are not official versions, and this site was not produced in affiliation with, or with the endorsement of, the Government of Canada.'),
      h('p', {}, 'Some websites refuse automated access, for example parts of UBC’s. We do not work around that, so those awards are missing until the provider agrees.'),
      CONTACT_EMAIL ? h('p', {}, 'If you run a program shown here and want something corrected or removed, write to ', h('a', { href: 'mailto:' + CONTACT_EMAIL }, CONTACT_EMAIL), '.') : null),
    section('Your privacy',
      h('p', {}, 'We do not ask for your name, contact details, status or membership numbers, or any documents. The answers you give are sent once to our service to filter the list; they are not saved, not logged and not shown in the address bar. Closing the tab clears them. This site sets no cookies and uses no trackers.')),
    section('Data and corrections',
      h('p', {}, 'The same information is available as open data: ', h('a', { href: '/opportunities' }, 'the list'), ' and ', h('a', { href: '/docs' }, 'the API documentation'), '.'),
      CONTACT_EMAIL ? h('p', {}, 'Found something out of date? ', h('a', { href: 'mailto:' + CONTACT_EMAIL }, CONTACT_EMAIL)) : null)));
}

export const loadingView = () => h('div', { class: 'page' }, h('div', { class: 'container' },
  h('p', { class: 'sr-only', id: 'page-title', tabindex: '-1' }, 'Loading scholarships'),
  h('div', { class: 'list' }, h('div', { class: 'skeleton' }), h('div', { class: 'skeleton' }), h('div', { class: 'skeleton' }))));

export const errorView = (error, retry) => h('div', { class: 'page' }, h('div', { class: 'container' }, h('div', { class: 'empty' },
  h('h1', { id: 'page-title', tabindex: '-1' }, 'We could not load the scholarships'),
  h('p', {}, error && error.message ? error.message : 'Something went wrong.'),
  h('p', { class: 'muted' }, 'Nothing you entered has been lost or saved. Check your connection and try again.'),
  h('button', { class: 'btn btn--primary', type: 'button', onClick: retry }, 'Try again'))));

export const notFoundView = () => h('div', { class: 'page' }, h('div', { class: 'container' }, h('div', { class: 'empty' },
  h('h1', { id: 'page-title', tabindex: '-1' }, 'That page does not exist'),
  h('p', {}, h('a', { class: 'btn btn--primary', href: '#/' }, 'Go to the start')))));