// End-to-end: the TV, guests' phones and the host remote, all against a real server.
import { expect, test } from "@playwright/test";

const PIN = "2468";
const HOST_SESSION = "e2e/.data/host.json"; // signed in once by global-setup.js
const PHONE = { viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true };

let videoNo = 0;
const nextVideo = () => `e2e${String(videoNo++).padStart(8, "0")}`; // 11 characters, like a YouTube id

/** A signed-in host context with a fresh event. */
async function hostWithEvent(browser, name, config = {}) {
  const ctx = await browser.newContext({ viewport: { width: 1600, height: 900 }, storageState: HOST_SESSION });
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
  await expect(tv.locator(".checks input")).toHaveCount(4); // the sign-in check runs first
  for (const box of await tv.locator(".checks input").all()) await box.check();
  await tv.getByRole("button", { name: "Continue" }).click();
  await expect(tv.locator(".join-card")).toBeVisible();
  return tv;
}

let phoneNo = 0;
/** A phone context with its own address, as on real Wi-Fi (the join limit is per address). */
const phoneContext = (browser) => browser.newContext({
  ...PHONE, extraHTTPHeaders: { "X-Forwarded-For": `10.20.${Math.floor(phoneNo / 250)}.${(phoneNo++ % 250) + 1}` },
});

async function joinPhone(browser, ev, name) {
  const ctx = await phoneContext(browser);
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

  // Dana joins mid-song: no jumping the line. She goes to the end of the singer order (after Blake,
  // before Alex's second song) and is announced as a new singer when her first song comes up.
  const dana = await joinPhone(browser, ev, "Dana");
  await queue(dana, "Ironic");
  expect((await state(api, ev)).queue.map((q) => q.guest_name)).toEqual(["Blake", "Dana", "Alex"]);
  await expect(tv.locator(".queue-item").nth(1)).toContainText("Dana");
  await expect(tv.locator(".queue-item").nth(1).locator(".new-tag")).toBeVisible();
  await finishSong(api, ev); // Alex done, Blake up
  await finishSong(api, ev); // Blake done, Dana's debut
  await expect(tv.locator(".newsinger-flash")).toContainText("Dana");
  expect((await state(api, ev)).queue.map((q) => q.guest_name)).toEqual(["Alex"]);

  // Phones show a wait estimate for each queued song.
  await alex.getByRole("button", { name: /My songs/ }).click();
  await expect(alex.locator(".mine-song .r-meta").first()).toContainText(/min|any moment/);

  // End of the night: the recap on the TV and on phones.
  tv.on("dialog", (d) => d.accept());
  await tv.mouse.move(800, 880);
  await tv.getByRole("button", { name: "End event" }).click();
  await expect(tv.locator(".recap")).toContainText("That's a wrap");
  // Alex's and Blake's songs, plus Dana's, which was on when the host ended the night.
  await expect(tv.locator(".recap-tile").first()).toHaveText(/^3\s*songs sung$/);
  await expect(alex.locator(".recap-me")).toContainText("You sang 1 song");
});

test("a voted Superset set, then the host bouches a singer and calls a smoke break", async ({ browser }) => {
  const { ctx, ev, api } = await hostWithEvent(browser, "Vote Night", { ready_seconds: 0 });
  const phones = {};
  for (const name of ["Alex", "Blake", "Casey"]) {
    phones[name] = await joinPhone(browser, ev, name);
    await queue(phones[name], `${name}'s song`);
  }
  const tv = await openTv(ctx, ev);
  await tv.getByRole("button", { name: "Start event" }).click();
  await expect(tv.locator(".now-singing")).toContainText("Alex");

  // Alex calls a Superset kicked off by their own song; the other two vote yes on their phones.
  await phones.Alex.getByRole("button", { name: "Call a Superset" }).click();
  await phones.Alex.locator(".chooser").getByRole("button", { name: /Start now/ }).click();
  await expect(tv.locator(".vote-panel")).toContainText("Alex");
  await expect(phones.Alex.locator(".vote-card")).toContainText("waiting for votes");
  await phones.Blake.getByRole("button", { name: "Yes!" }).click();
  await expect(tv.locator(".vote-panel")).toContainText("Yes 1");
  await phones.Casey.getByRole("button", { name: "Yes!" }).click();
  await expect(tv.locator(".superset-flash")).toContainText("SUPERSET!");
  await expect(tv.locator(".superset-panel")).toContainText("Songs like “Alex's song”");
  await expect(tv.locator(".superset-panel .set-slot").first()).toContainText("Alex");
  await expect(phones.Blake.locator(".set-card")).toContainText("your next pick is your Superset song");

  // Alex's song was the first of the set; the TV waits for Blake (next in the order) to pick.
  await finishSong(api, ev);
  await expect(tv.locator(".set-waiting")).toContainText("Waiting for Blake");
  await expect(phones.Blake.locator(".set-card")).toContainText("It's your turn!");
  await queue(phones.Blake, "Blake's Superset song");
  await expect(tv.locator(".now-singing")).toContainText("Blake's Superset song");
  phones.Casey.on("dialog", (d) => d.accept());
  await phones.Casey.getByRole("button", { name: "Sit this one out" }).click();
  await finishSong(api, ev); // set done: the queue carries on where it left off
  await expect(tv.locator(".superset-panel")).toBeHidden();
  await expect(tv.locator(".now-singing")).toContainText("Blake's song");

  // Bouche! from Host admin: Casey's out, and the TV makes sure everyone knows.
  let caseyAlert = "";
  phones.Casey.on("dialog", (d) => { caseyAlert = d.message(); });
  const admin = await ctx.newPage();
  admin.on("dialog", (d) => d.accept());
  await admin.goto("/host/admin");
  await admin.locator(".list-row", { hasText: "Casey" }).getByRole("button", { name: "Bouche!" }).click();
  await expect(tv.locator(".bouche-flash")).toContainText("Casey has been BOUCHED!");
  await expect.poll(() => caseyAlert).toContain("BOUCHED");
  expect((await state(api, ev)).guests.map((g) => g.name)).toEqual(["Alex", "Blake"]);

  // Smoke break: the song stops and goes back to the front; the TV and phones say so until Resume.
  await tv.mouse.move(800, 880);
  await tv.getByRole("button", { name: "Pause queue" }).click();
  await expect(tv.locator(".smoke-break")).toContainText("Smoke break!");
  await expect(phones.Blake.locator(".smoke-banner")).toBeVisible();
  expect((await state(api, ev)).queue[0].guest_name).toBe("Blake");
  await tv.mouse.move(800, 880);
  await tv.getByRole("button", { name: "Resume queue" }).click();
  await expect(tv.locator(".smoke-break")).toBeHidden();
  await expect(tv.locator(".now-singing")).toContainText("Blake");
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

  const ctx = await phoneContext(browser);
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

test("admin, event list and remote fit a phone screen", async ({ browser }) => {
  const { ev } = await hostWithEvent(browser, "Phone Admin Night");
  const ctx = await browser.newContext({ viewport: { width: 360, height: 800 }, isMobile: true, hasTouch: true,
    storageState: HOST_SESSION });
  const page = await ctx.newPage();
  const fits = async () => expect(await page.evaluate(() =>
    document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBeLessThanOrEqual(0);
  for (const tab of ["Events", "Themes", "YouTube", "Appearance", "Updates", "Security"]) {
    await page.goto("/host/admin");
    await page.getByRole("button", { name: tab, exact: true }).click();
    await page.waitForTimeout(300);
    await fits();
  }
  for (const path of ["/host", `/host/remote/${ev.id}`]) {
    await page.goto(path);
    await page.waitForLoadState("networkidle");
    await fits();
  }
});

test("crowd meter, last call and the recap's crowd favourite", async ({ browser }) => {
  const soon = new Date(Date.now() + 9 * 60 * 1000); // room for about two 4-minute songs
  const lastCall = `${String(soon.getHours()).padStart(2, "0")}:${String(soon.getMinutes()).padStart(2, "0")}`;
  const { ctx, ev, api } = await hostWithEvent(browser, "Cheer Night", { ready_seconds: 0, last_call: lastCall });
  const alex = await joinPhone(browser, ev, "Alex");
  const blake = await joinPhone(browser, ev, "Blake");
  await queue(alex, "Alex's song");
  const tv = await openTv(ctx, ev);
  await expect(tv.locator(".last-call-tag")).toContainText("room for about");
  await tv.getByRole("button", { name: "Start event" }).click();
  await expect(tv.locator(".now-singing")).toContainText("Alex's song");

  // Cheers fill the crowd meter on the TV.
  for (const e of ["🔥", "👏", "🎉"]) {
    await blake.getByRole("button", { name: `Send ${e}` }).click();
    await blake.waitForTimeout(400);
  }
  await expect(tv.locator(".crowd-meter")).toContainText("3");

  // Last call: songs that would run past closing time are refused, and the TV says so.
  let status = 200;
  for (let i = 0; i < 4 && status === 200; i += 1) {
    status = await blake.evaluate(async (videoId) => (await fetch("/api/guest/queue", {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${localStorage.getItem("kq_token")}` },
      body: JSON.stringify({ video_id: videoId }),
    })).status, nextVideo());
  }
  expect(status).toBe(409);
  await expect(tv.locator(".last-call-tag.closed")).toContainText("Last call!");
  await expect(blake.locator(".card .warning")).toContainText("Last call has passed");

  tv.on("dialog", (d) => d.accept());
  await tv.mouse.move(800, 880);
  await tv.getByRole("button", { name: "End event" }).click();
  await expect(tv.locator(".recap")).toContainText("Crowd favourite");
  await expect(tv.locator(".recap")).toContainText("Alex · Alex's song (3 cheers)");
  expect((await state(api, ev)).recap.most_cheered.singer).toBe("Alex");
});

test("Superset ideas on phones and backups in Host admin", async ({ browser }) => {
  const { ctx, ev, api } = await hostWithEvent(browser, "Ideas Night", { ready_seconds: 0 });
  const alex = await joinPhone(browser, ev, "Alex");
  const blake = await joinPhone(browser, ev, "Blake");
  await queue(alex, "Toto - Africa (Karaoke Version)");
  await api.post(`/api/host/events/${ev.id}/actions/start`);
  await api.post(`/api/host/events/${ev.id}/actions/superset-now`);
  // "Songs like Africa": Blake's phone suggests searches from the song that kicked it off.
  await expect(blake.locator(".set-card .idea-chip")).toHaveText(["Toto", "Africa"]);

  // Backups: make one, change something, restore it.
  const admin = await ctx.newPage();
  admin.on("dialog", (d) => d.accept());
  await admin.goto("/host/admin");
  await admin.getByRole("button", { name: "Backups", exact: true }).click();
  const made = await (await api.post("/api/host/backups")).json();
  await api.post("/api/host/events", { data: { name: "Made after the backup" } });
  await admin.reload();
  await admin.getByRole("button", { name: "Backups", exact: true }).click();
  await admin.locator(".list-row", { hasText: made.name }).getByRole("button", { name: "Restore" }).click();
  await expect(admin.locator(".toast")).toContainText("Restored");
  const names = (await (await api.get("/api/host/events")).json()).map((e) => e.name);
  expect(names).not.toContain("Made after the backup");
  expect(names).toContain("Ideas Night");
});

test("Main Stage banner on the TV and phones, a swapped-in upload and the join link preview", async ({ browser, request }) => {
  const { ctx, ev, api } = await hostWithEvent(browser, "Festival Night");
  await api.put("/api/host/appearance", { data: { scheme: "stage" } });
  const tv = await openTv(ctx, ev);
  await expect(tv.locator("html")).toHaveAttribute("data-banner", "");
  expect(await tv.locator(".tv-top").evaluate((el) => getComputedStyle(el).backgroundImage)).toContain("/banners/main-stage.jpg");
  expect(await tv.locator(".idle-overlay").evaluate((el) => getComputedStyle(el).backgroundImage)).toContain("/banners/main-stage.jpg");

  const joinCtx = await phoneContext(browser);
  const join = await joinCtx.newPage();
  await join.goto(`/join/${ev.join_code}`);
  await expect(join.locator(".join-hero")).toBeVisible();
  const page = await (await request.get(`/join/${ev.join_code}`)).text();
  expect(page).toContain('content="Join Festival Night on Karoulette"');
  expect(page).toMatch(/og:image" content="http[^"]+\/banners\/main-stage-og\.jpg"/);

  // Upload a banner in Host admin, then show it with every skin.
  const admin = await ctx.newPage();
  await admin.goto("/host/admin");
  await admin.getByRole("button", { name: "Appearance" }).click();
  const png = Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==", "base64");
  await admin.getByTestId("banner-file").setInputFiles({ name: "ours.png", mimeType: "image/png", buffer: png });
  await expect(admin.locator(".toast")).toContainText("New banner is up");
  await expect(admin.getByText("Your uploaded banner")).toBeVisible();
  await expect.poll(() => tv.locator(".tv-top").evaluate((el) => getComputedStyle(el).backgroundImage)).toContain("/api/public/banner?v=");
  await admin.getByText("Show my banner with every skin").click();
  await api.put("/api/host/appearance", { data: { scheme: "neon" } });
  await expect(tv.locator("html")).toHaveAttribute("data-scheme", "neon");
  await expect(tv.locator("html")).toHaveAttribute("data-banner", "");

  // Remove it: Neon goes back to no banner at all.
  admin.on("dialog", (d) => d.accept());
  await admin.getByRole("button", { name: "Remove my banner" }).click();
  await expect(tv.locator("html")).not.toHaveAttribute("data-banner", "");
  await api.put("/api/host/appearance/banner-all", { data: { on: false } });
});

test("song history: every event's songs, merged singer names, CSV export and the public page", async ({ browser }) => {
  const { ctx, ev, api } = await hostWithEvent(browser, "History Night", { ready_seconds: 0 });
  const al = await joinPhone(browser, ev, "Al");
  const alan = await joinPhone(browser, ev, "Alan");
  await queue(al, "Toto - Africa (Karaoke Version)");
  await queue(alan, "ABBA - Dancing Queen (Karaoke)");
  await api.post(`/api/host/events/${ev.id}/actions/start`);
  await finishSong(api, ev);
  await finishSong(api, ev);

  const admin = await ctx.newPage();
  await admin.goto("/host/admin");
  await admin.getByRole("button", { name: "Song history" }).click();
  const list = admin.locator(".history-table");
  await expect(list).toContainText("Toto - Africa");
  await expect(list).toContainText("History Night");

  // Al and Alan are the same person: merge them.
  await admin.getByText(/Singer names/).click();
  const nameRow = (n) => admin.locator(".name-list li").filter({ has: admin.locator("strong", { hasText: new RegExp(`^${n}$`) }) });
  await nameRow("Al").getByRole("checkbox").check();
  await nameRow("Alan").getByRole("checkbox").check();
  await admin.getByLabel("Show them as").fill("Alan");
  await admin.getByRole("button", { name: /Merge 2 names/ }).click();
  await expect(admin.locator(".toast")).toContainText("Merged 2 names as Alan");
  await expect(admin.locator(".chart-card", { hasText: "Top singers" })).toContainText("Alan");
  await expect(list).toContainText("(as Al)");

  const download = admin.waitForEvent("download");
  await admin.getByRole("button", { name: /Export all as CSV/ }).click();
  const csv = await (await download).createReadStream().then(async (s) => {
    let text = "";
    for await (const chunk of s) text += chunk;
    return text;
  });
  expect(csv).toContain("date,time,event,singer");
  expect(csv).toContain("History Night,Alan,,Toto - Africa (Karaoke Version)");

  // Guests can see it at /history until the host stops sharing it.
  const guestCtx = await phoneContext(browser);
  const guest = await guestCtx.newPage();
  await guest.goto("/history");
  await expect(guest.locator(".history-table")).toContainText("ABBA - Dancing Queen");
  await admin.getByText(/Share it with guests/).click();
  await guest.reload();
  await expect(guest.getByText("The host hasn't shared the song history.")).toBeVisible();
  await api.put("/api/host/history/public", { data: { on: true } });
});
