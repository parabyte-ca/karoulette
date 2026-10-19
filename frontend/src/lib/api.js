// Thin fetch wrapper. Guest calls send the bearer token; host calls rely on the HttpOnly cookie.
export class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.status = status;
  }
}

const TOKEN_KEY = "kq_token";
const CODE_KEY = "kq_code";

export const guestSession = {
  get token() {
    try { return localStorage.getItem(TOKEN_KEY); } catch { return null; }
  },
  get code() {
    try { return localStorage.getItem(CODE_KEY); } catch { return null; }
  },
  save(token, code) {
    try {
      localStorage.setItem(TOKEN_KEY, token);
      localStorage.setItem(CODE_KEY, code);
    } catch { /* private mode: session only lasts this tab */ }
  },
  clear() {
    try {
      localStorage.removeItem(TOKEN_KEY);
      localStorage.removeItem(CODE_KEY);
    } catch { /* ignore */ }
  },
};

export async function api(path, { method = "GET", body, guest = false, raw = false } = {}) {
  const headers = {};
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (guest && guestSession.token) headers.Authorization = `Bearer ${guestSession.token}`;
  let res;
  try {
    res = await fetch(path, {
      method,
      headers,
      credentials: "same-origin",
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
  } catch {
    throw new ApiError("Can't reach the KaraokeQueue server. Check your Wi-Fi.", 0);
  }
  if (raw) return res;
  let data = null;
  try { data = await res.json(); } catch { /* empty body */ }
  if (!res.ok) {
    let msg = data?.detail;
    if (Array.isArray(msg)) msg = msg.map((d) => d.msg).join("; ");
    throw new ApiError(msg || `Something went wrong (${res.status})`, res.status);
  }
  return data;
}

export const hostApi = {
  action: (eventId, action) => api(`/api/host/events/${eventId}/actions/${action}`, { method: "POST" }),
};
