// End-to-end: the TV, guests' phones and the host remote, all against a real server.
import { expect, test } from "@playwright/test";

const PIN = "2468";
const PHONE = { viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true };

let videoNo = 0;
const nextVideo = () => `e2e${String(videoNo++).padStart(8, "0")}`; // 11 characters, like a YouTube id

/** A signed-in host context with a fresh event. */
async function hostWithEvent(browser, name, config = {}) {
  const ctx = await browser.newContext({ viewport: { width: 1600, height: 900 } });
  const res = await ctx.request.post("/api/host/login", { data: { pin: PIN } });
  expect(res.ok()).toBeTruthy();
  const ev = await (await ctx.request.post("/api/host/events", {
    data: { name, config: { superset_chance: 0, autoplay: true, ...config } },
  })).json();
  return { ctx, ev, api: ctx.request };
}

/** Open the TV screen, tick the Premium checklist and keep YouTube out of it (no real videos in tests). */
async function openTv(ctx, ev) {
  const tv = await ctx.newPage();
  await tv.route(/youtube\.com|ytimg\.com|googlevideo\.com/, (route) => route.abort());
  await tv.goto(`/host/event/${ev.id}`);
  for (const box of await tv.locator(".checks input").all()) await box.check();
  await tv.getByRole("button", { name: "Continue" }).click();
  await expect(tv.locator(".join-card")).toBeVisible();
  return tv;
}

async function joinPhone(browser, ev, name) {
  const ctx = await browser.newContext(PHONE);
  const page = await ctx.newPage();
  await page.goto(`/join/${ev.join_code}`);
  await page.getByPlaceholder("What should the TV call you?").fill(name);
  await page.getByRole("button", { name: "Join the rotation" }).click();
  await expect(page.locator(".status-card")).toBeVisible();
  return page;
}

/** Queue a song from a phone through the API (search needs YouTube, which tests don't have). */
async function queue(phone, title, duetGuestId = null) {
  const status = await phone.evaluate(async ([videoId, t, duet]) => (await fetch("/api/guest/queue", {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${localStorage.getItem("kq_token")}` },
    body: JSON.stringify({ video_id: videoId, title: t, duet_guest_id: duet }),
  })).status, [nextVideo(), title, duetGuestId]);
  expect(status).toBe(200);
}

const state = async (api, ev) => (await api.get(`/api/host/events/${ev.id}/state`)).json();
const finishSong = async (api, ev) => {
  const s = await state(api, ev);
  await api.post(`/api/host/events/${ev.id}/player`, { data: { item_id: s.now_playing.id, state: "ended" } });
};

test("a night out: get ready, new singer, reactions and the recap", async ({ browser }) => {
  const { ctx, ev, api } = await hostWithEvent(browser, "E2E Night", { ready_seconds: 30 });
  const alex = await joinPhone(browser, ev, "Alex");
  const blake = await joinPhone(browser, ev, "Blake");
  await queue(alex, "Livin' On A Prayer");
  await queue(alex, "Africa");
  await queue(blake, "Take On Me");

  const tv = await openTv(ctx, ev);
  await tv.getByRole("button", { name: "Start event" }).click();

  // The "Get ready" countdown names the singer; the host can cut it short.
  await expect(tv.locator(".get-ready")).toContainText("Alex");
  await expect(tv.locator(".get-ready")).toContainText("Livin' On A Prayer");
  await expect(alex.locator(".status-big")).toContainText("You're up!");
  await expect(blake.locator(".status-big")).toContainText("Your song is up next!");
  await tv.getByRole("button", { name: "Start now" }).click();
  await expect(tv.locator(".get-ready")).toBeHidden();
  await expect(tv.locator(".now-singing")).toContainText("Now singing");

  // Cheers from a phone float up the TV.
  await blake.getByRole("button", { name: "Send 🔥" }).click();
  await expect(tv.locator(".reaction")).toContainText("Blake");

  // Dana joins mid-song: slotted in next, then announced as a new singer.
  const dana = await joinPhone(browser, ev, "Dana");
  await queue(dana, "Ironic");
  await expect(tv.locator(".queue-item").first()).toContainText("Dana");
  await expect(tv.locator(".queue-item").first().locator(".new-tag")).toBeVisible();
  await finishSong(api, ev);
  await expect(tv.locator(".newsinger-flash")).toContainText("Dana");
  expect((await state(api, ev)).queue.map((q) => q.guest_name)).toEqual(["Blake", "Alex"]);

  // Phones show a wait estimate for each queued song.
  await alex.getByRole("button", { name: /My songs/ }).click();
  await expect(alex.locator(".mine-song .r-meta").first()).toContainText(/min|any moment/);

  // End of the night: the recap on the TV and on phones.
  tv.on("dialog", (d) => d.accept());
  await tv.mouse.move(800, 880);
  await tv.getByRole("button", { name: "End event" }).click();
  await expect(tv.locator(".recap")).toContainText("That's a wrap");
  // Alex's first song, plus Dana's, which was on when the host ended the night.
  await expect(tv.locator(".recap-tile").first()).toHaveText(/^2\s*songs sung$/);
  await expect(alex.locator(".recap-me")).toContainText("You sang 1 song");
});

test("duets show both singers and reach the partner's phone", async ({ browser }) => {
  const { ctx, ev, api } = await hostWithEvent(browser, "Duet Night", { ready_seconds: 0 });
  const blake = await joinPhone(browser, ev, "Blake");
  const casey = await joinPhone(browser, ev, "Casey");
  const caseyId = (await state(api, ev)).guests.find((g) => g.name === "Casey").id;
  await queue(blake, "Islands in the Stream", caseyId);
  await expect(casey.locator(".toast")).toContainText("added you to a duet");
  await expect(casey.getByText("Duets you're in")).toBeVisible();

  const tv = await openTv(ctx, ev);
  await tv.getByRole("button", { name: "Start event" }).click();
  await expect(tv.locator(".now-singing")).toContainText("Blake & Casey");
  await expect(casey.locator(".status-big")).toContainText("singing now");
});

test("song limit per singer", async ({ browser }) => {
  const { ev } = await hostWithEvent(browser, "Limit Night", { max_songs_per_singer: 1 });
  const alex = await joinPhone(browser, ev, "Alex");
  await queue(alex, "First pick");
  const status = await alex.evaluate(async (videoId) => (await fetch("/api/guest/queue", {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${localStorage.getItem("kq_token")}` },
    body: JSON.stringify({ video_id: videoId }),
  })).status, nextVideo());
  expect(status).toBe(409);
  await expect(alex.locator(".card .warning")).toContainText("the most the host allows");
});

test("rejoin on a new phone keeps your place and signs the old phone out", async ({ browser }) => {
  const { ev } = await hostWithEvent(browser, "Rejoin Night");
  const oldPhone = await joinPhone(browser, ev, "Alex");
  await queue(oldPhone, "Bohemian Rhapsody");
  const code = (await oldPhone.locator(".rejoin-code").textContent()).trim();
  expect(code).toMatch(/^[A-Z0-9]{6}$/);
  let signedOut = "";
  oldPhone.on("dialog", (d) => { signedOut = d.message(); d.accept(); });

  const ctx = await browser.newContext(PHONE);
  const newPhone = await ctx.newPage();
  await newPhone.goto(`/join/${ev.join_code}`);
  await newPhone.getByRole("button", { name: /Switched phones/ }).click();
  await newPhone.locator(".code-input").fill(code);
  await newPhone.getByRole("button", { name: "Rejoin" }).click();
  await expect(newPhone.locator(".phone-me")).toContainText("Alex");
  await expect(newPhone.getByRole("button", { name: "My songs (1)" })).toBeVisible();
  await expect.poll(() => signedOut).toContain("another phone");
});

test("host remote on a phone controls the TV", async ({ browser }) => {
  const { ctx, ev, api } = await hostWithEvent(browser, "Remote Night", { ready_seconds: 0 });
  const alex = await joinPhone(browser, ev, "Alex");
  await queue(alex, "Song One");
  await queue(alex, "Song Two");
  const tv = await openTv(ctx, ev);

  const remoteCtx = await browser.newContext(PHONE);
  const remote = await remoteCtx.newPage();
  await remote.goto(`/host/remote/${ev.id}`);
  await remote.locator("input[type=password]").fill(PIN);
  await remote.getByRole("button", { name: "Sign in" }).click();
  await remote.getByRole("button", { name: "Start event" }).click();
  await expect(tv.locator(".now-singing")).toContainText("Song One");
  await remote.getByRole("button", { name: "Skip" }).click();
  await expect(tv.locator(".now-singing")).toContainText("Song Two");
  expect((await state(api, ev)).now_playing.title).toBe("Song Two");
  await remote.getByRole("button", { name: "Volume up" }).click(); // the TV ignores it with no player loaded
  await expect(remote.locator(".status-card")).toContainText("Song Two");
});

test("installable app and colour schemes", async ({ browser, request }) => {
  const manifest = await (await request.get("/manifest.webmanifest")).json();
  expect(manifest.start_url).toBe("/join");
  expect(manifest.icons.some((i) => i.purpose === "maskable")).toBeTruthy();
  const sw = await request.get("/sw.js");
  expect(sw.headers()["cache-control"]).toBe("no-cache");
  expect(await sw.text()).not.toContain("__KAROULETTE_VERSION__");
  expect((await request.get("/icon-192.png")).headers()["content-type"]).toBe("image/png");

  const { ev, api } = await hostWithEvent(browser, "Disco Night");
  const phone = await joinPhone(browser, ev, "Alex");
  await expect(phone.locator('link[rel="manifest"]')).toHaveCount(1);
  await api.put("/api/host/appearance", { data: { scheme: "disco" } });
  await expect(phone.locator("html")).toHaveAttribute("data-scheme", "disco");
  await api.put("/api/host/appearance", { data: { scheme: "neon" } });
});
