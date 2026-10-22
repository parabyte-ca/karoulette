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

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  event.waitUntil(self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((windows) => {
    const open = windows.find((w) => "focus" in w);
    return open ? open.focus() : self.clients.openWindow("/join");
  }));
});
