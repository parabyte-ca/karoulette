// README screenshots: two nights of made-up singers on a running server, shot on the TV, a phone and Host admin.
// Use a throwaway server (empty database, YouTube blocked is fine): npm run screenshots -- http://127.0.0.1:8095 1234
// Set PUBLIC_BASE_URL on that server (e.g. https://karaoke.example.ca) so the QR codes don't show a local address.
import { fileURLToPath } from "node:url";
import { chromium } from "@playwright/test";

const B = process.argv[2] || "http://127.0.0.1:8095";
const PIN = process.argv[3] || "1234";
const OUT = fileURLToPath(new URL("../../docs/screenshots", import.meta.url));
const b = await chromium.launch();
const THUMB = '<svg xmlns="http://www.w3.org/2000/svg" width="320" height="180"><defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#ff3d8b"/><stop offset="1" stop-color="#2bd4ff"/></linearGradient></defs><rect width="320" height="180" fill="url(#g)"/><text x="160" y="105" font-size="56" text-anchor="middle" fill="white">🎤</text></svg>';
const thumbs = (r) => (/ytimg/.test(r.request().url()) ? r.fulfill({ contentType: "image/svg+xml", body: THUMB }) : r.abort());
const shot = (p, name) => p.screenshot({ path: `${OUT}/${name}.jpg`, type: "jpeg", quality: 82 });
const host = await b.newContext({ viewport: { width: 1600, height: 900 } });
const api = host.request;
await api.post(`${B}/api/host/login`, { data: { pin: PIN } });
let vid = 0; const v = () => `shot${String(vid++).padStart(7, "0")}`;
const songs = ["ABBA - Dancing Queen (Karaoke)", "Toto - Africa (Karaoke)", "Queen - Bohemian Rhapsody (Karaoke)", "Adele - Hello (Karaoke)", "Journey - Don't Stop Believin' (Karaoke)", "Whitney Houston - I Wanna Dance with Somebody (Karaoke)", "Shania Twain - Man! I Feel Like a Woman (Karaoke)", "Bon Jovi - Livin' On A Prayer (Karaoke)"];
const H = (t) => ({ Authorization: `Bearer ${t}` });
async function night(name, people, perSinger, end, config = {}) {
  const ev = await (await api.post(`${B}/api/host/events`, { data: { name, config: { superset_chance: 0, ready_seconds: 0, ...config } } })).json();
  const t = {};
  for (const p of people) t[p] = await (await api.post(`${B}/api/guest/join`, { data: { code: ev.join_code, name: p } })).json();
  for (let i = 0; i < perSinger; i++) for (const p of people)
    await api.post(`${B}/api/guest/queue`, { headers: H(t[p].token), data: { video_id: v(), title: songs[(i * 3 + people.indexOf(p)) % songs.length] } });
  await api.post(`${B}/api/host/events/${ev.id}/actions/start`);
  if (end) {
    for (let n = 0; ; n++) { const s = await (await api.get(`${B}/api/host/events/${ev.id}/state`)).json(); if (!s.now_playing) break;
      for (const p of people.slice(0, 2)) await api.post(`${B}/api/guest/react`, { headers: H(t[p].token), data: { emoji: "🔥" } });
      await api.post(`${B}/api/host/events/${ev.id}/player`, { data: { item_id: s.now_playing.id, state: "ended" } }); }
    await api.post(`${B}/api/host/events/${ev.id}/actions/end`);
  }
  return { ev, t };
}
const recap = await night("Halloween Bash", ["Alex", "Blake", "Casey", "Dana"], 2, true);
const { ev, t } = await night("Friday Night", ["Alex", "Blake", "Casey", "Dana", "Eli"], 2, false, { themes_enabled: true, ready_seconds: 30 });

const tv = await host.newPage();
await tv.route(/youtube\.com|ytimg\.com|googlevideo\.com/, thumbs);
await tv.goto(`${B}/host/event/${ev.id}`);
await tv.locator(".checks input").nth(3).waitFor();
for (const box of await tv.locator(".checks input").all()) await box.check();
await tv.getByRole("button", { name: "Continue" }).click();
await tv.locator(".get-ready").waitFor();
await tv.waitForTimeout(6000);
await shot(tv, "tv-get-ready");
await tv.goto(`${B}/host/event/${recap.ev.id}`);
await tv.locator(".recap-overlay").waitFor();
await tv.waitForTimeout(1500);
await shot(tv, "tv-recap");

const phoneCtx = await b.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true, deviceScaleFactor: 2 });
await phoneCtx.addInitScript(([tok, c]) => { localStorage.setItem("kq_token", tok); localStorage.setItem("kq_code", c); }, [t.Casey.token, ev.join_code]);
await phoneCtx.route(/ytimg\.com/, thumbs);
const ph = await phoneCtx.newPage();
await ph.goto(`${B}/join/${ev.join_code}`);
await ph.locator(".status-card").waitFor();
await ph.waitForTimeout(6000);
await shot(ph, "phone-home");
await ph.getByRole("button", { name: /^Queue/ }).click();
await shot(ph, "phone-queue");
await ph.goto(`${B}/help`);
await ph.locator("#when summary").click();
await shot(ph, "phone-help");

const admin = await host.newPage();
await admin.goto(`${B}/host/admin`);
await admin.getByRole("heading", { name: /Settings for/ }).waitFor();
await shot(admin, "admin-events");
await b.close();
