// Playlists from what was sung: a YouTube playlist link of the original recordings, or a Spotify playlist
// made in the listener's own account. Spotify sign-in uses PKCE in the browser, so the server never
// sees anyone's Spotify login.
import { api } from "./api";

const YT_MAX = 50; // YouTube's watch_videos link takes up to 50 videos
const BATCH = 5; // originals looked up per request (each may be a search)

/** YouTube playlist links for a list of video ids: one per 50 videos. */
export function youtubeLinks(videoIds) {
  const links = [];
  for (let i = 0; i < videoIds.length; i += YT_MAX) {
    links.push(`https://www.youtube.com/watch_videos?video_ids=${videoIds.slice(i, i + YT_MAX).join(",")}`);
  }
  return links;
}

/** Look up the original recording of each song, a few at a time. `code` scopes it to one event. */
export async function findOriginals(itemIds, code, onProgress) {
  const out = [];
  for (let i = 0; i < itemIds.length; i += BATCH) {
    const found = await api("/api/public/playlist/originals", {
      method: "POST", body: { item_ids: itemIds.slice(i, i + BATCH), code: code || null },
    });
    out.push(...found);
    onProgress?.(Math.min(itemIds.length, i + BATCH), itemIds.length);
  }
  return out;
}

let config = null;
export const resetPlaylistConfig = () => { config = null; };
export async function playlistConfig() {
  if (!config) config = api("/api/public/playlist-config").catch(() => ({ spotify_client_id: "" }));
  return config;
}

// ------------------------------------------------------------------ Spotify

const SPOTIFY_KEY = "kq_spotify";
const SCOPES = "playlist-modify-private playlist-modify-public";
export const spotifyRedirect = () => `${window.location.origin}/spotify`;
/** Spotify only signs in on HTTPS (or this computer's 127.0.0.1). */
export const spotifyUsable = () => window.location.protocol === "https:" || window.location.hostname === "127.0.0.1";

const b64url = (bytes) => btoa(String.fromCharCode(...new Uint8Array(bytes)))
  .replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
const randomString = (n) => b64url(crypto.getRandomValues(new Uint8Array(n)));

/** Send the listener to Spotify to sign in; `job` ({name, description, tracks, returnTo}) runs on return. */
export async function startSpotify(clientId, job) {
  const verifier = randomString(48);
  const state = randomString(16);
  const challenge = b64url(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(verifier)));
  sessionStorage.setItem(SPOTIFY_KEY, JSON.stringify({ verifier, state, job, clientId }));
  const params = new URLSearchParams({
    response_type: "code", client_id: clientId, scope: SCOPES, redirect_uri: spotifyRedirect(),
    code_challenge_method: "S256", code_challenge: challenge, state,
  });
  window.location.assign(`https://accounts.spotify.com/authorize?${params}`);
}

async function spotifyFetch(token, path, options = {}) {
  for (let attempt = 0; attempt < 3; attempt++) {
    const res = await fetch(`https://api.spotify.com/v1${path}`, {
      ...options,
      headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json", ...(options.headers || {}) },
    });
    if (res.status === 429) { // rate limited: wait as asked, then try again
      await new Promise((r) => setTimeout(r, (Number(res.headers.get("Retry-After")) || 2) * 1000));
      continue;
    }
    return res;
  }
  throw new Error("Spotify is busy right now. Try again in a minute.");
}

async function spotifyJson(token, path, options) {
  const res = await spotifyFetch(token, path, options);
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw Object.assign(new Error(body?.error?.message || `Spotify said no (${res.status})`), { status: res.status });
  return body;
}

/** Finish signing in (on /spotify) and make the playlist. Returns {url, added, missed, name, returnTo}. */
export async function finishSpotify(search, onProgress) {
  const saved = JSON.parse(sessionStorage.getItem(SPOTIFY_KEY) || "null");
  const params = new URLSearchParams(search);
  if (!saved) throw new Error("This Spotify sign-in has expired. Go back and try again.");
  if (params.get("error")) throw Object.assign(new Error("Spotify sign-in was cancelled."), { returnTo: saved.job.returnTo });
  if (params.get("state") !== saved.state) throw new Error("This Spotify sign-in doesn't match. Go back and try again.");
  sessionStorage.removeItem(SPOTIFY_KEY); // the code works once
  const tokenRes = await fetch("https://accounts.spotify.com/api/token", {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({
      grant_type: "authorization_code", code: params.get("code") || "", redirect_uri: spotifyRedirect(),
      client_id: saved.clientId, code_verifier: saved.verifier,
    }),
  });
  const tokenBody = await tokenRes.json().catch(() => ({}));
  if (!tokenRes.ok) throw new Error(tokenBody.error_description || "Spotify sign-in failed.");
  return { ...(await makeSpotifyPlaylist(tokenBody.access_token, saved.job, onProgress)), returnTo: saved.job.returnTo };
}

async function makeSpotifyPlaylist(token, job, onProgress) {
  const me = await spotifyJson(token, "/me");
  const uris = [];
  const missed = [];
  for (const [i, track] of job.tracks.entries()) {
    const q = encodeURIComponent(track.replace(/\s+-\s+/g, " "));
    const found = await spotifyJson(token, `/search?q=${q}&type=track&limit=1`);
    const uri = found?.tracks?.items?.[0]?.uri;
    if (uri) { if (!uris.includes(uri)) uris.push(uri); } else missed.push(track);
    onProgress?.(i + 1, job.tracks.length);
  }
  if (!uris.length) throw new Error("Spotify couldn't find any of these songs.");
  const body = JSON.stringify({ name: job.name.slice(0, 100), description: job.description.slice(0, 300), public: false });
  let playlist;
  try {
    playlist = await spotifyJson(token, `/users/${encodeURIComponent(me.id)}/playlists`, { method: "POST", body });
  } catch (e) {
    if (![403, 404].includes(e.status)) throw e;
    playlist = await spotifyJson(token, "/me/playlists", { method: "POST", body });
  }
  for (let i = 0; i < uris.length; i += 100) {
    const chunk = JSON.stringify({ uris: uris.slice(i, i + 100) });
    try {
      await spotifyJson(token, `/playlists/${playlist.id}/tracks`, { method: "POST", body: chunk });
    } catch (e) {
      if (![403, 404, 410].includes(e.status)) throw e;
      await spotifyJson(token, `/playlists/${playlist.id}/items`, { method: "POST", body: chunk });
    }
  }
  return { url: playlist.external_urls?.spotify, added: uris.length, missed, name: job.name };
}
