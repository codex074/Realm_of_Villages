// Thin fetch wrapper around the /api JSON contract (see BUILD.md §9).

export class ApiError extends Error {
  // code: machine-readable error code, message: Thai user-facing text, status: HTTP status.
  constructor(code, message, status) {
    super(message);
    this.name = 'ApiError';
    this.code = code;
    this.message = message;
    this.status = status;
  }
}

async function request(method, path, body) {
  let res;
  try {
    res = await fetch(`/api${path}`, {
      method,
      headers: body !== undefined ? { 'Content-Type': 'application/json' } : undefined,
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
  } catch {
    throw new ApiError('NETWORK', 'เชื่อมต่อเซิร์ฟเวอร์ไม่ได้', 0);
  }
  if (!res.ok) {
    let code = 'HTTP_ERROR';
    let message = `เกิดข้อผิดพลาด (${res.status})`;
    try {
      const data = await res.json();
      if (data && typeof data === 'object' && data.error && typeof data.error === 'object') {
        code = data.error.code ?? code;
        message = data.error.message ?? message;
      }
    } catch {
      // Non-JSON error body: keep the generic message.
    }
    if (res.status === 401 && code === 'UNAUTHENTICATED') window.dispatchEvent(new Event('auth-required'));
    throw new ApiError(code, message, res.status);
  }
  if (res.status === 204) return null;
  return res.json();
}

export const api = {
  get: (path) => request('GET', path),
  post: (path, body) => request('POST', path, body),
  patch: (path, body) => request('PATCH', path, body),
  del: (path) => request('DELETE', path),
};
