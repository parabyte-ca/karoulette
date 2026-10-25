// Karoulette service worker: lets phones install the app, opens it quickly and shows song alerts.
// Live data (/api, /ws) always comes from the network. The server fills in the version below, so each
// release starts a fresh cache.
const CACHE = "karoulette-__KAROULETTE_VERSION__";
const SHELL = ["/", "/favicon.svg", "/icon-192.png", "/manifest.webmanifest"];

self.addEventListener("install", (event) => {
  self.skipWaiting();
  event.waitUntil(caches.open(CACHE).then((cache) => cache.addAll(SHELL)).catch(() => {}));
});

self.addEventListener("activate", (event) => {
  event.waitUntil(caches.keys()
    .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
    .then(() => self.clients.claim()));
});

const store = (key, response) => {
  if (response.ok) {
    const copy = response.clone();
    caches.open(CACHE).then((cache) => cache.put(key, copy));
  }
  return response;
};

self.addEventListener("fetch", (event) => {
  const req = event.request;
  const url = new URL(req.url);
  if (req.method !== "GET" || url.origin !== self.location.origin) return;
  if (url.pathname.startsWith("/api/") || url.pathname.startsWith("/ws/")) return;
  if (url.pathname.startsWith("/assets/")) {
    // Built files have hashed names, so a cached copy is always right.
    event.respondWith(caches.match(req).then((hit) => hit || fetch(req).then((res) => store(req, res))));
  } else if (req.mode === "navigate") {
    // Network first so a new release shows straight away; offline, fall back to the cached app shell.
    event.respondWith(fetch(req).then((res) => store("/", res)).catch(() => caches.match("/")));
  }
});

// Push alerts from the server ({title, body, url, tag}). When Karoulette is open on screen the page's own
// toast already says it, so skip the system notification there (except on Apple devices, which drop
// alerts for sites whose pushes show nothing).
const apple = /iphone|ipad|ipod|macintosh/i.test(self.navigator.userAgent);
self.addEventListener("push", (event) => {
  let data = {};
  try { data = event.data ? event.data.json() : {}; } catch { data = { title: "Karoulette", body: event.data?.text() || "" }; }
  event.waitUntil(self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((windows) => {
    if (!apple && windows.some((w) => w.visibilityState === "visible" && w.focused)) return undefined;
    return self.registration.showNotification(data.title || "Karoulette", {
      body: data.body || "", icon: "/icon-192.png", badge: "/icon-192.png", tag: data.tag || "karoulette",
      renotify: true, vibrate: [300, 150, 300], data: { url: data.url || "/join" },
    });
  }));
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const url = event.notification.data?.url || "/join";
  event.waitUntil(self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((windows) => {
    const open = windows.find((w) => "focus" in w);
    if (!open) return self.clients.openWindow(url);
    const there = new URL(open.url).pathname === url;
    return there || !("navigate" in open) ? open.focus() : open.navigate(url).then((w) => (w || open).focus());
  }));
});
