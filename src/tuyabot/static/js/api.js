/** Klien HTTP tipis untuk REST API dashboard. */

export class ApiError extends Error {
  constructor(status, message) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
  }
}

async function request(path, options = {}) {
  const response = await fetch(path, {
    credentials: 'same-origin',
    headers: options.body ? { 'Content-Type': 'application/json' } : undefined,
    ...options,
  });

  if (response.status === 401) {
    throw new ApiError(401, 'Sesi berakhir, silakan masuk lagi.');
  }

  let payload = null;
  const contentType = response.headers.get('content-type') || '';
  if (contentType.includes('application/json')) {
    payload = await response.json().catch(() => null);
  }

  if (!response.ok) {
    const detail = payload && payload.detail ? payload.detail : `Permintaan gagal (${response.status})`;
    throw new ApiError(response.status, detail);
  }
  return payload;
}

export const api = {
  get: (path) => request(path),
  post: (path, body) => request(path, { method: 'POST', body: JSON.stringify(body ?? {}) }),
};

export async function getSession() {
  try {
    return await api.get('/api/session');
  } catch {
    return { authenticated: false };
  }
}

export function login(apiKey) {
  return api.post('/api/login', { api_key: apiKey });
}

export function logout() {
  return api.post('/api/logout');
}
