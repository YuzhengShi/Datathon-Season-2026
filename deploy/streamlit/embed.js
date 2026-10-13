// Runs inside the Streamlit component frame that hosts the site (see streamlit_app.py).
// Outside Streamlit it does nothing. Inside, it
//  - tells Streamlit the frame is ready,
//  - keeps the site in its static mode (there is no backend here),
//  - lets the page scroll: Streamlit builds this frame with scrolling="no", so the frame's own viewport never scrolls and the body
//    scrolls instead (embed.css); the scroll calls of the site are pointed at the body,
//  - switches the search box to keyword search, because AI search needs the backend.
(function () {
  if (window.parent === window) return;
  window.parent.postMessage({ isStreamlitMessage: true, type: 'streamlit:componentReady', apiVersion: 1 }, '*');

  // The site asks /api/health first; with no backend it should find out at once and stay in its static mode.
  const realFetch = window.fetch.bind(window);
  window.fetch = (url, options) => (String(url).startsWith('/api/') ? Promise.reject(new TypeError('This online version has no backend.')) : realFetch(url, options));

  const onBody = (method) => (x, y) => document.body[method](typeof x === 'object' && x !== null ? x : { left: x, top: y });
  window.scrollTo = onBody('scrollTo');
  window.scroll = window.scrollTo;
  window.scrollBy = onBody('scrollBy');

  document.documentElement.classList.add('in-streamlit');
  document.addEventListener('DOMContentLoaded', () => {
    const mode = document.querySelector('#search-mode');
    const input = document.querySelector('#funding-search');
    const icon = document.querySelector('#search-form use');
    if (mode) mode.value = 'keyword';
    if (input) input.placeholder = 'Search by name, provider or keyword…';
    if (icon) icon.setAttribute('href', '#i-search');
  });
})();
