// Runs inside the Streamlit component frame that hosts the site (see streamlit_app.py).
// It tells Streamlit the frame is ready, makes the frame as tall as the window, and turns off the parts of the site that need the backend
// (AI search and chat), which this online version does not have. Outside Streamlit it does nothing.
(function () {
  if (window.parent === window) return;
  const send = (type, data) => window.parent.postMessage({ isStreamlitMessage: true, type, ...data }, '*');

  // The site asks /api/health first; here there is no backend, so it should find out at once and stay in its static mode.
  const realFetch = window.fetch.bind(window);
  window.fetch = (url, options) => (String(url).startsWith('/api/') ? Promise.reject(new TypeError('This online version has no backend.')) : realFetch(url, options));

  const fit = () => {
    let height = 900;
    try { height = window.parent.innerHeight; } catch (error) { /* the parent window is not readable */ }
    send('streamlit:setFrameHeight', { height: Math.max(560, height) });
  };
  send('streamlit:componentReady', { apiVersion: 1 });
  fit();
  try { window.parent.addEventListener('resize', fit); } catch (error) { /* ignore */ }

  document.documentElement.classList.add('in-streamlit');
  document.addEventListener('DOMContentLoaded', () => {
    // Keyword search instead of the AI mode, with a placeholder that fits it.
    const mode = document.querySelector('#search-mode');
    const input = document.querySelector('#funding-search');
    const icon = document.querySelector('#search-form use');
    if (mode) mode.value = 'keyword';
    if (input) input.placeholder = 'Search by name, provider or keyword…';
    if (icon) icon.setAttribute('href', '#i-search');
  });
})();
