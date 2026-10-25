// Web Push: alerts that reach the phone even when Karoulette isn't open or the screen is locked.
// The browser makes a subscription with the server's public key; the server stores it against tonight's
// guest and sends each alert through the phone's push service (Google, Apple or Mozilla).
import { api } from "./api";

export const KINDS = [
  ["turn", "Up next and you're up", "Two songs to go, up next, and grab the mic"],
  ["superset", "Superset turns and votes", "Your Superset pick, and when someone calls a vote"],
  ["duet", "Duets, suggestions and song issues", "A duet invite, a song suggested for you, or a song that couldn't play"],
  ["playlist", "End-of-night playlist", "Tonight's songs as a playlist when the event ends"],
];
export const DEFAULT_PREFS = Object.fromEntries(KINDS.map(([k]) => [k, true]));
const PREFS_KEY = "kq_push_prefs";

const isStandalone = () => window.matchMedia?.("(display-mode: standalone)").matches || window.navigator.standalone;
const isIos = () => /iphone|ipad|ipod/i.test(window.navigator.userAgent)
  || (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1); // iPadOS says it's a Mac

export const pushSupported = () => window.isSecureContext && "serviceWorker" in navigator && "PushManager" in window
  && "Notification" in window;
/** iPhones only allow alerts from Karoulette once it's on the Home Screen (iOS 16.4 or later). */
export const iosNeedsInstall = () => isIos() && !isStandalone() && !pushSupported();

export const savedPrefs = () => {
  try { return JSON.parse(localStorage.getItem(PREFS_KEY) || "null"); } catch { return null; }
};
const keepPrefs = (prefs) => {
  try {
    if (prefs) localStorage.setItem(PREFS_KEY, JSON.stringify(prefs));
    else localStorage.removeItem(PREFS_KEY);
  } catch { /* private mode */ }
};
/** True when this phone gets push alerts, so the page needn't show its own notifications too. */
export const pushActive = () => !!savedPrefs() && "Notification" in window && Notification.permission === "granted";

const toBytes = (b64) => {
  const s = atob(b64.replace(/-/g, "+").replace(/_/g, "/") + "=".repeat((4 - (b64.length % 4)) % 4));
  return Uint8Array.from(s, (c) => c.charCodeAt(0));
};

async function registration() {
  const reg = await Promise.race([
    navigator.serviceWorker.ready,
    new Promise((_, reject) => setTimeout(() => reject(new Error("Alerts need the Karoulette app to finish loading. Try again in a moment.")), 8000)),
  ]);
  return reg;
}

async function send(sub, prefs) {
  const json = sub.toJSON();
  const r = await api("/api/guest/push", { method: "POST", guest: true,
    body: { endpoint: json.endpoint, keys: json.keys, prefs } });
  keepPrefs(r.prefs);
  return r.prefs;
}

/** Ask permission, subscribe and tell the server. Returns the saved prefs. */
export async function enablePush(prefs = DEFAULT_PREFS) {
  const result = await Notification.requestPermission();
  if (result !== "granted") {
    throw new Error("Alerts are blocked for Karoulette. Allow notifications in your phone's settings, then try again.");
  }
  const reg = await registration();
  const { key } = await api("/api/public/push-key");
  const options = { userVisibleOnly: true, applicationServerKey: toBytes(key) };
  let sub;
  try {
    sub = await reg.pushManager.subscribe(options);
  } catch (e) {
    // Subscribed before with another server key (a restored backup): start over with this one.
    const old = await reg.pushManager.getSubscription();
    if (!old) throw e;
    await old.unsubscribe();
    sub = await reg.pushManager.subscribe(options);
  }
  return send(sub, prefs);
}

/** After joining an event: move this phone's alerts to tonight's guest. Returns prefs, or null when off. */
export async function syncPush() {
  const prefs = savedPrefs();
  if (!prefs || !pushSupported() || Notification.permission !== "granted") return null;
  try {
    const sub = await (await registration()).pushManager.getSubscription();
    if (!sub) { keepPrefs(null); return null; }
    return await send(sub, prefs);
  } catch { return null; }
}

export async function setPushPrefs(prefs) {
  const sub = await (await registration()).pushManager.getSubscription();
  if (!sub) throw new Error("Alerts are off on this phone. Turn them on again.");
  const r = await api("/api/guest/push/prefs", { method: "PUT", guest: true, body: { endpoint: sub.endpoint, prefs } });
  keepPrefs(r.prefs);
  return r.prefs;
}

export async function disablePush() {
  keepPrefs(null);
  const sub = await (await registration()).pushManager.getSubscription().catch(() => null);
  if (!sub) return;
  await api("/api/guest/push/off", { method: "POST", guest: true, body: { endpoint: sub.endpoint } }).catch(() => {});
  await sub.unsubscribe().catch(() => {});
}
