// The only module that talks to the network. Same origin as the page: the API serves this app.
export class ApiError extends Error {
  constructor(message, { kind, status } = {}) { super(message); this.name = 'ApiError'; this.kind = kind; this.status = status; }
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

export const getInstitutions = () => request('/reference/institutions');
export const getOpportunities = () => request('/opportunities?limit=100');
export const getDetail = (id) => request('/opportunities/' + encodeURIComponent(id));
/** The profile travels in the body of one request; the service neither stores nor logs it, and neither does this app. */
export const postMatch = (profile) => request('/match', { method: 'POST', body: { profile, limit: 100 } });