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
  // Closing in 9-10 minutes (HH:MM drops the seconds): room for Alex's 4-minute song and one more, never
  // less than 8 minutes away (which would already be last call) and never 12 (room for a third).
  const soon = new Date(Date.now() + 10 * 60 * 1000);
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

test("playlists: an event's page, the TV recap QR, the phone recap and saving to Spotify", async ({ browser }) => {
  const { ctx, ev, api } = await hostWithEvent(browser, "Playlist Night", { ready_seconds: 0 });
  await api.put("/api/host/playlists/spotify", { data: { client_id: "e2eclientid" } });
  const tv = await openTv(ctx, ev);
  const phone = await joinPhone(browser, ev, "Rae");
  await queue(phone, "Africa (In the Style of Toto) (Karaoke Version)");
  await queue(phone, "Queen - Bohemian Rhapsody (Karaoke)");
  await api.post(`/api/host/events/${ev.id}/actions/start`);
  await finishSong(api, ev);
  await finishSong(api, ev);
  await api.post(`/api/host/events/${ev.id}/actions/end`);
  await expect(tv.locator(".recap-playlist img")).toHaveAttribute("src", new RegExp(`page=playlist`));
  await expect(phone.getByRole("button", { name: /YouTube playlist \(2\)/ })).toBeVisible();

  // The playlist page: no search in tests, so the karaoke videos stand in for the originals.
  const page = await phone.context().newPage();
  await page.goto(`/playlist/${ev.join_code}`);
  await expect(page.locator(".playlist-tracks li")).toHaveCount(2);
  await expect(page.locator(".playlist-tracks")).toContainText("Toto - Africa");
  await page.getByRole("button", { name: /YouTube playlist/ }).click();
  const link = page.getByRole("link", { name: /Open on YouTube/ });
  await expect(link).toHaveAttribute("href", /^https:\/\/www\.youtube\.com\/watch_videos\?video_ids=e2e\d{8},e2e\d{8}$/);

  // Spotify, with Spotify itself stood in for.
  const origin = new URL(page.url()).origin;
  const added = [];
  const cors = { "Access-Control-Allow-Origin": "*", "Access-Control-Allow-Headers": "authorization, content-type",
                 "Access-Control-Allow-Methods": "GET, POST, OPTIONS" };
  await page.context().route("https://accounts.spotify.com/**", async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname === "/authorize") {
      expect(url.searchParams.get("redirect_uri")).toBe(`${origin}/spotify`);
      return route.fulfill({ contentType: "text/html", body: `<script>location.replace(${JSON.stringify(
        `${origin}/spotify?code=c1&state=${url.searchParams.get("state")}`)})</script>` });
    }
    if (route.request().method() === "OPTIONS") return route.fulfill({ status: 204, headers: cors });
    expect(route.request().postData()).toContain("code_verifier=");
    return route.fulfill({ headers: cors, json: { access_token: "tok" } });
  });
  await page.context().route("https://api.spotify.com/**", async (route) => {
    const req = route.request();
    if (req.method() === "OPTIONS") return route.fulfill({ status: 204, headers: cors });
    const path = new URL(req.url()).pathname;
    if (path === "/v1/me") return route.fulfill({ headers: cors, json: { id: "rae" } });
    if (path === "/v1/search") {
      const q = new URL(req.url()).searchParams.get("q");
      return route.fulfill({ headers: cors, json: { tracks: { items: [{ uri: `spotify:track:${q.length}` }] } } });
    }
    if (path === "/v1/users/rae/playlists") {
      return route.fulfill({ headers: cors, json: { id: "pl1", external_urls: { spotify: "https://open.spotify.com/playlist/pl1" } } });
    }
    if (path === "/v1/playlists/pl1/tracks") { added.push(...req.postDataJSON().uris); return route.fulfill({ headers: cors, json: {} }); }
    return route.fulfill({ status: 404, headers: cors, json: {} });
  });
  await page.getByRole("button", { name: "Spotify playlist" }).click();
  await expect(page.getByRole("link", { name: /Open in Spotify/ })).toHaveAttribute("href", "https://open.spotify.com/playlist/pl1");
  await expect(page.getByText(/is in your Spotify with 2 songs/)).toBeVisible();
  expect(added).toHaveLength(2);
  await page.getByRole("link", { name: "← Back" }).click();
  await expect(page).toHaveURL(new RegExp(`/playlist/${ev.join_code}$`));
  await api.put("/api/host/playlists/spotify", { data: { client_id: "" } });
});

test("timeline, archive and delete for good in Host admin", async ({ browser }) => {
  const { ctx, ev, api } = await hostWithEvent(browser, "Timeline Night", { ready_seconds: 0 });
  const phone = await joinPhone(browser, ev, "Rae");
  await queue(phone, "Toto - Africa (Karaoke Version)");
  await api.post(`/api/host/events/${ev.id}/actions/start`);
  await api.post(`/api/host/events/${ev.id}/actions/skip-song`);
  await api.post(`/api/host/events/${ev.id}/actions/end`);

  const admin = await ctx.newPage();
  await admin.goto("/host/admin");
  await admin.getByRole("button", { name: /Timeline Night/ }).click();
  const timeline = admin.locator(".timeline");
  await expect(timeline).toContainText("Rae added “Toto - Africa”, round 1");
  await expect(timeline).toContainText("Skipped “Toto - Africa” (Rae)");
  await admin.getByLabel("Who").selectOption("Rae");
  await expect(timeline.locator("li")).toHaveCount(3);          // joined, got a singer code, added

  await admin.getByRole("button", { name: "🗄 Archive" }).click();
  await expect(admin.locator(".toast")).toContainText("Archived");
  await expect(admin.getByRole("button", { name: "Unarchive" })).toBeVisible();
  const picker = await ctx.newPage();
  await picker.goto("/host");
  await expect(picker.getByText("Timeline Night")).toHaveCount(0);   // hidden from the TV's list

  admin.once("dialog", (d) => d.accept("wrong name"));
  await admin.getByRole("button", { name: "Delete for good" }).click();
  await expect(admin.locator(".toast", { hasText: "nothing was deleted" })).toBeVisible();
  admin.once("dialog", (d) => d.accept("Timeline Night"));
  await admin.getByRole("button", { name: "Delete for good" }).click();
  await expect.poll(async () => (await (await api.get("/api/host/events")).json()).some((e) => e.id === ev.id)).toBe(false);
});

test("returning singers: code saved on the phone, past songs, claiming and host disputes", async ({ browser }) => {
  const first = await hostWithEvent(browser, "Code Night One", { ready_seconds: 0 });
  const phoneCtx = await phoneContext(browser);
  const phone = await phoneCtx.newPage();
  await phone.goto(`/join/${first.ev.join_code}`);
  await phone.getByPlaceholder("What should the TV call you?").fill("Zed");
  await phone.getByRole("button", { name: "Join the rotation" }).click();
  await expect(phone.locator(".singer-card")).toContainText("Your singer code:");
  const code = (await phone.locator(".singer-card .singer-code").textContent()).trim();
  await queue(phone, "Toto - Africa (Karaoke Version)");
  await first.api.post(`/api/host/events/${first.ev.id}/actions/start`);
  await finishSong(first.api, first.ev);
  await first.api.post(`/api/host/events/${first.ev.id}/actions/end`);

  // Next event, same phone: it knows the singer and offers their past songs.
  const second = await hostWithEvent(browser, "Code Night Two", { ready_seconds: 0 });
  await phone.goto(`/join/${second.ev.join_code}`);
  await expect(phone.locator(".welcome-back")).toContainText(`Welcome back, Zed! Singer code ${code}`);
  await expect(phone.getByPlaceholder("What should the TV call you?")).toHaveValue("Zed");
  await phone.getByPlaceholder("What should the TV call you?").fill("Zed P");
  await phone.getByRole("button", { name: "Join the rotation" }).click();
  await expect(phone.locator(".phone-footer")).toContainText(`Your singer code: ${code}`);
  await expect(phone.locator(".phone-footer")).toContainText("2 nights so far");
  await phone.locator(".past-songs summary").click();
  await expect(phone.locator(".past-songs")).toContainText("Toto - Africa");

  // Someone else claims "Zed" by name: it's already Zed P's, so the host decides.
  const other = await joinPhone(browser, second.ev, "Bob");
  await other.getByRole("button", { name: "Claim my past nights" }).click();
  await other.locator(".claim-list li").filter({ has: other.locator("strong", { hasText: /^Zed$/ }) }).getByRole("checkbox").check();
  await other.getByRole("button", { name: /Claim 1 name/ }).click();
  await expect(other.locator(".toast", { hasText: "the host will decide" })).toBeVisible();

  const admin = await second.ctx.newPage();
  await admin.goto("/host/admin");
  await admin.getByRole("button", { name: "Song history" }).click();
  const panel = admin.locator(".names-panel", { hasText: "Singers and codes" });
  await expect(panel.locator(".disputes")).toContainText("Bob");
  await panel.getByRole("button", { name: "Keep" }).click();
  await expect(admin.locator(".toast", { hasText: "Kept with Zed P" })).toBeVisible();
  await expect(admin.locator(".history-table")).toContainText("(as Zed)");
});

test("push alerts: pick kinds, turn on, follow the phone to a new event, the service worker shows them", async ({ browser }) => {
  const { ctx: hostCtx, ev, api } = await hostWithEvent(browser, "Push Night", { autoplay: false });
  const ctx = await phoneContext(browser);
  // Headless Chromium has no push service and always reports notifications as blocked: allow them, and hand
  // out a subscription with real keys instead.
  await ctx.addInitScript(() => {
    Object.defineProperty(Notification, "permission", { get: () => "granted" });
    Notification.requestPermission = async () => "granted";
    const b64 = (buf) => btoa(String.fromCharCode(...new Uint8Array(buf))).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
    const endpoint = "https://fcm.googleapis.com/fcm/send/e2e-test";
    const wrap = (keys) => keys && { endpoint, toJSON: () => ({ endpoint, keys }),
      unsubscribe: async () => { localStorage.removeItem("e2e_push"); return true; } };
    PushManager.prototype.getSubscription = async () => wrap(JSON.parse(localStorage.getItem("e2e_push")));
    PushManager.prototype.subscribe = async () => {
      const pair = await crypto.subtle.generateKey({ name: "ECDH", namedCurve: "P-256" }, true, ["deriveBits"]);
      const keys = { p256dh: b64(await crypto.subtle.exportKey("raw", pair.publicKey)), auth: b64(crypto.getRandomValues(new Uint8Array(16))) };
      localStorage.setItem("e2e_push", JSON.stringify(keys));
      return wrap(keys);
    };
  });
  const page = await ctx.newPage();
  await page.goto(`/join/${ev.join_code}`);
  await page.getByPlaceholder("What should the TV call you?").fill("Pia");
  await page.getByRole("button", { name: "Join the rotation" }).click();
  await page.getByRole("button", { name: "🔔 Buzz me when I'm nearly up" }).click();
  await expect(page.locator(".alert-kinds input")).toHaveCount(4);
  await page.getByLabel(/End-of-night playlist/).uncheck();
  const saved = page.waitForResponse((r) => r.url().endsWith("/api/guest/push") && r.request().method() === "POST");
  await page.getByRole("button", { name: "Turn on alerts" }).click();
  expect((await (await saved).json()).prefs).toEqual({ turn: true, superset: true, duet: true, playlist: false });
  await expect(page.locator(".toast", { hasText: "Alerts on" })).toBeVisible();
  await expect(page.getByRole("button", { name: "🔔 Buzz me when I'm nearly up" })).toHaveCount(0);

  await page.locator(".alerts-settings summary").click();
  const changed = page.waitForResponse((r) => r.url().endsWith("/api/guest/push/prefs"));
  await page.locator(".alerts-settings").getByLabel(/Duets, suggestions/).uncheck();
  expect((await (await changed).json()).prefs.duet).toBe(false);

  // The same phone at the next event: its alerts move to the new guest by themselves.
  const next = await (await api.post("/api/host/events", { data: { name: "Push Night 2", config: { superset_chance: 0 } } })).json();
  await page.evaluate(() => { localStorage.removeItem("kq_token"); localStorage.removeItem("kq_code"); });
  await page.goto(`/join/${next.join_code}`);
  await page.getByPlaceholder("What should the TV call you?").fill("Pia");
  const moved = page.waitForResponse((r) => r.url().endsWith("/api/guest/push") && r.request().method() === "POST");
  await page.getByRole("button", { name: "Join the rotation" }).click();
  expect((await (await moved).json()).prefs).toEqual({ turn: true, superset: true, duet: false, playlist: false });

  // A push arriving while Karoulette isn't on screen becomes a notification that opens the right page.
  // (Headless Chromium can't show notifications, so record what the worker asks for.)
  const worker = ctx.serviceWorkers()[0] || await ctx.waitForEvent("serviceworker");
  await page.goto("about:blank");
  await worker.evaluate(() => {
    self.shown = [];
    self.registration.showNotification = async (title, options) => { self.shown.push({ title, ...options }); };
    self.dispatchEvent(Object.assign(new Event("push"), {
      data: { json: () => ({ title: "You're up next!", body: "Head to the mic", url: "/join/ABCD", tag: "karoulette-turn" }) },
      waitUntil: () => {},
    }));
  });
  await expect.poll(() => worker.evaluate(() => self.shown.map((n) => `${n.title}|${n.body}|${n.tag}|${n.data.url}`)))
    .toEqual(["You're up next!|Head to the mic|karoulette-turn|/join/ABCD"]);

  await page.goto(`/join/${next.join_code}`);
  await page.locator(".alerts-settings summary").click();
  await page.getByRole("button", { name: "Turn alerts off" }).click();
  await expect(page.getByRole("button", { name: "🔔 Buzz me when I'm nearly up" })).toBeVisible();
  await hostCtx.close();
});

test("likes on the queue and TV, a suggested song, then the recap and awards", async ({ browser }) => {
  const { ctx, ev, api } = await hostWithEvent(browser, "Love Night", { ready_seconds: 0 });
  const tv = await openTv(ctx, ev);
  const lou = await joinPhone(browser, ev, "Lou");
  const mo = await joinPhone(browser, ev, "Mo");
  await queue(lou, "Dolly Parton - Jolene (Karaoke)");

  // Mo likes Lou's song: the count shows on the TV and on Lou's phone, and nothing moves.
  await mo.getByRole("button", { name: /^Queue/ }).click();
  await mo.getByRole("button", { name: /Like Dolly Parton - Jolene/ }).click();
  await expect(mo.locator(".like-btn.liked")).toHaveText("❤️ 1");
  await expect(tv.locator(".queue-item .like-badge")).toHaveText("❤️ 1");
  await expect(lou.locator(".mine-song .r-meta")).toContainText("❤️ 1");

  // Lou suggests a song to Mo from search results (search is stubbed: tests have no YouTube).
  await lou.route(/\/api\/guest\/search/, (route) => route.fulfill({ json: { query: "abba karaoke", source: "api", results: [
    { video_id: nextVideo(), title: "ABBA - Waterloo (Karaoke Version)", channel: "Sing King", duration_s: 170, thumbnail: "", embeddable: true },
  ] } }));
  await lou.getByPlaceholder("Song or artist").fill("abba");
  await lou.getByRole("button", { name: "Search", exact: true }).click();
  await lou.locator(".duet-pick select").selectOption({ label: "🎁 Suggest it to Mo" });
  await lou.getByRole("button", { name: "🎁 Suggest" }).click();
  await expect(lou.locator(".toast", { hasText: "Suggested to Mo" })).toBeVisible();
  await mo.getByRole("button", { name: /^My songs/ }).click();
  await expect(mo.locator(".toast", { hasText: "Lou suggests you sing" })).toBeVisible();
  await mo.locator(".suggestions").getByRole("button", { name: "Add" }).click();
  await expect(mo.locator(".suggestions")).toHaveCount(0);
  await expect(mo.locator(".mine-song")).toContainText("Waterloo");
  await expect(lou.locator(".toast", { hasText: "Mo added your suggestion" })).toBeVisible();

  // The night ends: the recap names the most-loved song and the first-nighters; awards and bests follow.
  await api.post(`/api/host/events/${ev.id}/actions/start`);
  await finishSong(api, ev);
  await finishSong(api, ev);
  await api.post(`/api/host/events/${ev.id}/actions/end`);
  await expect(tv.locator(".recap-highlights")).toContainText("❤️ Most loved");
  await expect(tv.locator(".recap-highlights")).toContainText("Lou · Dolly Parton - Jolene (Karaoke) (1 like)");
  await expect(tv.locator(".recap-highlights")).toContainText(/First night!.*Lou, Mo/);
  await expect(mo.locator(".my-bests")).toContainText("First night! 🎉");

  const guest = await (await phoneContext(browser)).newPage();
  await guest.goto("/history");
  await expect(guest.locator(".awards")).toContainText("All-time records");
  await expect(guest.locator(".awards")).toContainText("Newest voices");
  await expect(guest.locator(".award-card", { hasText: "Newest voices" })).toContainText("Lou");
});

test("help page, and the singer and host tours on first visit", async ({ browser }) => {
  const tours = () => localStorage.setItem("kq_tours", "on"); // test browsers skip tours unless asked

  // Help: search, switch to hosts, and a deep link straight to one answer.
  const helpCtx = await browser.newContext(PHONE);
  const help = await helpCtx.newPage();
  await help.goto("/help");
  await expect(help.getByRole("heading", { name: "Singing tonight" })).toBeVisible();
  await help.getByLabel("Search help").fill("duet");
  await expect(help.locator("details.faq[open] summary").first()).toContainText("duet");
  await help.getByRole("button", { name: "📺 Hosts" }).click();
  await help.getByLabel("Search help").fill("forgot PIN");
  await expect(help.locator("details.faq[open] summary")).toHaveText(["Where's the host PIN? I forgot it"]);
  await help.goto("/help#switch");
  await expect(help.locator("#switch")).toHaveAttribute("open", "");
  await expect(help.locator("#switch")).toContainText("rejoin code");

  // Singer tour: shows once after joining, steps through the phone, and can be replayed.
  const { ctx, ev } = await hostWithEvent(browser, "Tour Night");
  const phoneCtx = await phoneContext(browser);
  await phoneCtx.addInitScript(tours);
  const phone = await phoneCtx.newPage();
  await phone.goto(`/join/${ev.join_code}`);
  await phone.getByPlaceholder("What should the TV call you?").fill("Alex");
  await phone.getByRole("button", { name: "Join the rotation" }).click();
  const tour = phone.getByRole("dialog", { name: "Singer tour" });
  await expect(tour).toContainText("Welcome, Alex!");
  await tour.getByRole("button", { name: "Next" }).click();
  await expect(tour).toContainText("Your turn at a glance");
  await expect(phone.locator(".tour-hole")).toBeVisible();
  for (let i = 0; i < 4; i++) await tour.getByRole("button", { name: "Next" }).click();
  await expect(tour).toContainText("Questions?");
  await tour.getByRole("button", { name: "Let's sing!" }).click();
  await expect(tour).toBeHidden();
  await phone.reload();
  await expect(phone.locator(".status-card")).toBeVisible();
  await expect(tour).toBeHidden();
  await phone.getByRole("button", { name: "🧭 Show me around" }).click();
  await expect(tour).toContainText("Welcome, Alex!");
  await phone.keyboard.press("Escape");
  await expect(tour).toBeHidden();

  // Host tour: the event list first, then the TV screen with its controls held open.
  await ctx.addInitScript(tours);
  const picker = await ctx.newPage();
  await picker.goto("/host");
  const hostTour = picker.getByRole("dialog", { name: "Host tour" });
  await expect(hostTour).toContainText("Welcome, host!");
  await hostTour.getByRole("button", { name: "Skip tour" }).click();
  await expect(hostTour).toBeHidden();

  const tv = await openTv(ctx, ev);
  const tvTour = tv.getByRole("dialog", { name: "TV screen tour" });
  await expect(tvTour).toContainText("This is the TV screen");
  await tv.keyboard.press("n"); // the tour keeps the TV's shortcuts from firing underneath
  for (let i = 0; i < 3; i++) await tvTour.getByRole("button", { name: "Next" }).click();
  await expect(tvTour).toContainText("Your controls");
  await expect(tv.locator("footer.controls")).not.toHaveClass(/hidden/);
  await tv.waitForTimeout(6500); // longer than the controls take to hide
  await expect(tv.locator("footer.controls")).not.toHaveClass(/hidden/);
  for (let i = 0; i < 3; i++) await tvTour.getByRole("button", { name: "Next" }).click();
  await expect(tvTour).toContainText("Help is here");
  await tvTour.getByRole("button", { name: "Let's go!" }).click();
  await expect(tvTour).toBeHidden();
  await tv.mouse.move(400, 400);
  await tv.getByRole("button", { name: "Help" }).click();
  await expect(tv.getByRole("dialog", { name: "Help" })).toContainText("Keyboard shortcuts");
  await helpCtx.close();
  await phoneCtx.close();
  await ctx.close();
});

test("no Content-Security-Policy violations on any screen", async ({ browser }) => {
  const { ctx, ev } = await hostWithEvent(browser, "CSP Night", { themes_enabled: true });
  const violations = [];
  const watch = (page) => page.on("console", (m) => {
    if (/Content Security Policy|Content-Security-Policy/i.test(m.text())) violations.push(`${page.url()}: ${m.text()}`);
  });
  ctx.on("page", watch);
  const phone = await joinPhone(browser, ev, "Alex");
  watch(phone);
  await queue(phone, "Africa");
  const tv = await openTv(ctx, ev);
  await tv.getByRole("button", { name: "Start event" }).click();
  for (const path of ["/", "/help", "/host", "/host/admin", `/host/remote/${ev.id}`, `/playlist/${ev.join_code}`, "/history", "/spotify"]) {
    const page = await ctx.newPage();
    await page.goto(path);
    await page.waitForLoadState("networkidle");
    await page.close();
  }
  await phone.reload();
  await expect(phone.locator(".status-card")).toBeVisible();
  expect(violations).toEqual([]);
});

test("TV announcements stay on top of the video, inside their band, on every skin layout", async ({ browser }) => {
  const { ctx, ev, api } = await hostWithEvent(browser, "Bouche Night");
  // Main Stage, Disco and Aurora lift the page above a background effect; that once dragged the announcements under the video.
  await api.put("/api/host/appearance", { data: { scheme: "stage" } });
  const alex = await joinPhone(browser, ev, "Alex");
  await joinPhone(browser, ev, "Jean-Christophe Tremblay"); // the longest name a guest can have
  await queue(alex, "Africa");
  const tv = await openTv(ctx, ev);
  await tv.setViewportSize({ width: 1024, height: 768 }); // the tightest TV layout
  await tv.getByRole("button", { name: "Start event" }).click();

  // Worst spill over the animation: past the band's top or bottom, or into its faded ends (8% each side). A band that
  // isn't fixed to the screen, or text with something else drawn over it, counts as a big spill.
  const spill = () => tv.evaluate(() => {
    const band = document.querySelector(".superset-flash");
    if (!band) return null;
    if (getComputedStyle(band).position !== "fixed") return 1000;
    const b = band.getBoundingClientRect();
    const fade = b.width * 0.08;
    band.style.pointerEvents = "auto"; // let elementFromPoint see the band
    const covered = [...band.children].flatMap((el) => [...el.getClientRects()]).some((r) => [0.2, 0.5, 0.8].some((f) => {
      const hit = document.elementFromPoint(r.left + r.width * f, r.top + r.height / 2);
      return hit && !band.contains(hit);
    }));
    band.style.pointerEvents = "";
    if (covered) return 500;
    return Math.max(...[...band.children].flatMap((el) => {
      const range = document.createRange();
      range.selectNodeContents(el);
      return [...range.getClientRects()].map((r) => Math.max(b.top - r.top, r.bottom - b.bottom, b.left + fade - r.left, r.right - (b.right - fade)));
    }));
  });
  const worst = async () => {
    await expect(tv.locator(".superset-flash")).toBeVisible();
    await tv.waitForTimeout(500); // slid in
    let most = -Infinity;
    for (let i = 0; i < 15; i++) { most = Math.max(most, (await spill()) ?? -Infinity); await tv.waitForTimeout(70); }
    return most;
  };

  const s = await state(api, ev);
  const victim = s.guests.find((g) => g.name.startsWith("Jean"));
  await api.post(`/api/host/events/${ev.id}/guests/${victim.id}/remove`);
  await expect(tv.locator(".bouche-flash")).toContainText("Jean-Christophe Tremblay has been BOUCHED!");
  expect(await worst()).toBeLessThanOrEqual(1);
  await expect(tv.locator(".superset-flash")).toBeHidden({ timeout: 10_000 });

  await api.put("/api/host/appearance", { data: { scheme: "neon" } });
  await api.post(`/api/host/events/${ev.id}/actions/superset-after`);
  expect(await worst()).toBeLessThanOrEqual(1);
});
