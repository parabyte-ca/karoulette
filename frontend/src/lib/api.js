// Thin fetch wrapper. Guest calls send the bearer token; host calls rely on the HttpOnly cookie.
export class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.status = status;
  }
}

const TOKEN_KEY = "kq_token";
const CODE_KEY = "kq_code";
const SINGER_KEY = "kq_singer";
const PAST_KEY = "kq_past_tokens"; // every event this phone joined: proves it was there when claiming past nights

const readJson = (key, fallback) => {
  try { return JSON.parse(localStorage.getItem(key) || "null") ?? fallback; } catch { return fallback; }
};

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
      const past = readJson(PAST_KEY, []).filter((t) => t !== token);
      localStorage.setItem(PAST_KEY, JSON.stringify([token, ...past].slice(0, 30)));
    } catch { /* private mode: session only lasts this tab */ }
  },
  /** Tokens from earlier events on this phone (and the current one, which may be from a past event). */
  get pastTokens() {
    const past = readJson(PAST_KEY, []);
    const current = this.token;
    return current && !past.includes(current) ? [current, ...past] : past;
  },
  /** The phone's singer code: {code, name}. Kept when an event ends, so the next event knows you. */
  get singer() { return readJson(SINGER_KEY, null); },
  saveSinger(singer) {
    try {
      if (singer?.code) localStorage.setItem(SINGER_KEY, JSON.stringify({ code: singer.code, name: singer.name }));
      else localStorage.removeItem(SINGER_KEY);
    } catch { /* private mode */ }
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
    throw new ApiError("Can't reach the Karoulette server. Check your Wi-Fi.", 0);
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
