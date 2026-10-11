// The only script that talks to the network. Same origin as the page: the API that serves this app also serves the data.
(function (root) {
  'use strict';

  class ApiError extends Error {
    constructor(message, { kind, status } = {}) {
      super(message);
      this.name = 'ApiError';
      this.kind = kind;
      this.status = status;
    }
  }

  async function request(path, { method = 'GET', body, timeout = 20000 } = {}) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeout);
    try {
      const response = await fetch(path, {
        method, signal: controller.signal, credentials: 'omit', cache: 'no-store',
        headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
        body: body === undefined ? undefined : JSON.stringify(body),
      });
      if (!response.ok) throw new ApiError(`The service answered ${response.status}.`, { kind: 'http', status: response.status });
      return await response.json();
    } catch (error) {
      if (error instanceof ApiError) throw error;
      if (error && error.name === 'AbortError') throw new ApiError('The service took too long to answer.', { kind: 'timeout' });
      throw new ApiError('Could not reach the service.', { kind: 'network' });
    } finally {
      clearTimeout(timer);
    }
  }

  // The service answers at most 100 records per request; keep asking until everything has arrived.
  const PAGE = 100;
  const MAX_PAGES = 20;

  async function allPages(fetchPage) {
    const results = [];
    let first = null;
    for (let page = 0; page < MAX_PAGES; page += 1) {
      const answer = await fetchPage(results.length);
      first = first || answer;
      const got = answer.results || [];
      results.push(...got);
      if (!got.length || results.length >= answer.total) break;
    }
    return { ...first, results };
  }

  const getInstitutions = () => request('/reference/institutions');
  const getOpportunities = () => allPages((offset) => request(`/opportunities?limit=${PAGE}&offset=${offset}`));
  const getDetail = (id) => request('/opportunities/' + encodeURIComponent(id));
  /** The profile travels in the body of one request; the service neither stores nor logs it, and neither does this app. */
  const postMatch = (profile) => allPages((offset) => request('/match', { method: 'POST', body: { profile, limit: PAGE, offset } }));

  root.FundingApi = { ApiError, getInstitutions, getOpportunities, getDetail, postMatch };
})(globalThis);
