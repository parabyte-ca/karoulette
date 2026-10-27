// The Help page's questions and answers. Each answer is a list of paragraphs; **bold** and `code` are formatted,
// and a paragraph starting with "1. " or "- " joins a numbered or bulleted list.

export const SINGER_HELP = [
  {
    title: "Getting started",
    items: [
      { id: "join", q: "How do I join?", a: [
        "Scan the QR code on the TV with your phone's camera, or open the address under it and type the five-letter event code.",
        "Pick a display name (it's what the TV calls you) and tap **Join the rotation**. No account, app or email needed.",
      ] },
      { id: "add-song", q: "How do I add a song?", a: [
        "On **My songs**, type a song or artist in the search box and tap **Add** beside the one you want. We add “karaoke” to your search for you.",
        "You can add songs before the host starts, and as many as you like (unless the host has set a limit).",
      ] },
      { id: "when", q: "When will I sing?", a: [
        "Everyone sings in the **singer order**: the order people joined. Each round, every singer with a song waiting sings once, then the next round starts.",
        "Your status card shows how many songs are before yours and roughly how long that is. The **Queue** tab shows the whole line-up.",
      ] },
      { id: "late", q: "I joined late. Do I have to wait for everyone?", a: [
        "New singers go to the end of the singer order, so your first song plays at the end of the current round. The TV gives you a “NEW SINGER!” welcome.",
      ] },
      { id: "no-app", q: "Do I need to install anything?", a: [
        "No, it runs in your phone's browser. If you like, tap **📲 Install Karoulette** (or on iPhone: Share, then “Add to Home Screen”) to keep it one tap away. On iPhone that's also needed for alerts.",
      ] },
    ],
  },
  {
    title: "Your songs",
    items: [
      { id: "order-songs", q: "Can I change which of my songs comes first?", a: [
        "Yes. Under **Your songs**, tap ▲ to sing one sooner. Your songs keep your place in the singer order; ▲ only changes which one you sing next.",
      ] },
      { id: "remove-song", q: "How do I remove a song?", a: ["Tap ✕ beside it under **Your songs**."] },
      { id: "not-ready", q: "It's nearly my turn and I'm not ready", a: [
        "When your song is up next, tap **Not ready? Let the next singer go first**. Your song plays straight after theirs.",
      ] },
      { id: "cant-find", q: "I can't find my song", a: [
        "Try the artist and the song title together, or fewer words. Searches look for karaoke versions on YouTube; some songs just don't have one.",
        "If the TV has **themes** on, the **Need ideas?** buttons search for songs that fit.",
      ] },
      { id: "taken", q: "Why does a song say “Taken” or “Already sung tonight”?", a: [
        "The host can stop the same song being sung twice in one night. Pick a different version or another song.",
      ] },
      { id: "refused", q: "Why was my song refused?", a: [
        "The host may have set a longest video length, a limit on how many songs each singer can have waiting, or a closing time (**last call**). The message under the search box says which.",
      ] },
      { id: "song-error", q: "My song couldn't play", a: [
        "Some videos can't be played outside YouTube. Your phone tells you when that happens: pick another song and it plays straight away, without losing your turn.",
      ] },
      { id: "past-songs", q: "Can I sing a song from last time again?", a: [
        "Yes. If you have a singer code, **Your past songs** on My songs lists everything you've sung here before, one tap to add.",
      ] },
    ],
  },
  {
    title: "Duets and suggestions",
    items: [
      { id: "duet", q: "How do I sing a duet?", a: [
        "Before you tap **Add**, set **Sing it** to “As a duet with…” and pick your partner. It plays on your turn, and your partner's phone gets a heads-up.",
        "Your partner can step out with ✕ under **Duets you're in**; you keep the song.",
      ] },
      { id: "suggest", q: "Can I suggest a song to someone?", a: [
        "Yes. Set **Sing it** to “🎁 Suggest it to…”, then tap **🎁 Suggest**. It appears on their phone to add or pass. You can have three suggestions waiting with each person.",
      ] },
      { id: "suggested", q: "Someone suggested a song to me", a: [
        "It's in the **Suggested for you** card on My songs. Add it to your songs, or pass. Nobody is told you passed.",
      ] },
    ],
  },
  {
    title: "Themes and Supersets",
    items: [
      { id: "themes", q: "What's the round theme?", a: [
        "When the host switches themes on, each round spins a theme, like “Disco” or “Power ballads”. It's only a suggestion: sing what you like.",
      ] },
      { id: "superset", q: "What's a Superset?", a: [
        "A bonus round where everyone sings one extra song that fits a theme, in singer order. Your other songs keep their places.",
        "When it starts, your next pick is your **Superset song**. Use **Change my pick** to swap it, or **Sit this one out** to pass. Off-theme? Anyone can tap ⚑ to flag it for the host.",
      ] },
      { id: "call-superset", q: "How do I call a Superset?", a: [
        "Tap **★ Call a Superset** on your status card. Choose a theme spun after this song, or songs like the one playing. Everyone else votes, and most votes wins.",
        "Each singer can call one vote per round.",
      ] },
    ],
  },
  {
    title: "Alerts, cheers and likes",
    items: [
      { id: "alerts", q: "Can my phone buzz when I'm nearly up?", a: [
        "Yes. Tap **🔔 Buzz me when I'm nearly up**, pick which alerts you want, and allow notifications. They reach your phone even when it's locked.",
        "Change or turn them off at the bottom of the page under **🔔 Alerts are on**.",
      ] },
      { id: "alerts-iphone", q: "Alerts don't work on my iPhone", a: [
        "iPhones only allow alerts from apps on the Home Screen. Tap Share, then **Add to Home Screen**, open Karoulette from there and turn alerts on. It needs iOS 16.4 or later.",
        "Alerts also need the site to be on a secure (https) address. If the button doesn't appear, ask the host.",
      ] },
      { id: "no-buzz", q: "I turned alerts on but nothing arrives", a: [
        "Check that notifications are allowed for your browser (or the Karoulette app) in your phone's settings, and that Focus or Do Not Disturb isn't on.",
        "The page itself still shows a banner and vibrates when you're up while it's open.",
      ] },
      { id: "cheers", q: "What are the emoji buttons?", a: [
        "While someone sings, tap the emoji at the bottom of your screen to cheer. They float up the TV and fill the crowd meter.",
      ] },
      { id: "likes", q: "How do likes work?", a: [
        "Tap ❤️ beside anyone's song in the **Queue** tab (or the song playing now). Likes show on the TV, and the night's recap names the most loved song.",
      ] },
    ],
  },
  {
    title: "Phones, codes and leaving",
    items: [
      { id: "closed", q: "I closed the page. Am I still in?", a: [
        "Yes. Open the same link (or scan the QR code again) on the same phone and you're back where you were.",
      ] },
      { id: "switch", q: "I switched phones or my battery died", a: [
        "Your **rejoin code** is at the bottom of your screen. On the new phone, open the join page, tap **Switched phones? Rejoin with your code**, and enter the event code and your rejoin code. You keep your place and songs.",
        "Lost the code? The host can see it in Host admin. Signing in on a new phone signs the old one out.",
      ] },
      { id: "singer-code", q: "What's my singer code?", a: [
        "A six-character code saved on your phone that remembers you from night to night: your past songs, personal bests and awards.",
        "On another phone, tap **Have a singer code?** when you join. **Claim past nights** adds nights you sang under other names (honour system: only your own!).",
      ] },
      { id: "removed", q: "It says I've been BOUCHED", a: ["The host removed you from the event. Talk to the host if you think it was a mistake."] },
      { id: "smoke", q: "The music stopped for a smoke break", a: [
        "The host paused the queue. Keep adding songs: everything carries on in the same order when the break ends.",
      ] },
      { id: "leave", q: "How do I leave?", a: [
        "Tap **Leave event** at the bottom of the page. Your songs waiting in the queue are removed.",
      ] },
    ],
  },
  {
    title: "After the night",
    items: [
      { id: "recap", q: "What happens when the night ends?", a: [
        "The TV and your phone show a recap: songs sung, the crowd favourite, the most loved song and awards.",
        "**Take the night home** turns every song into a YouTube or Spotify playlist of the original recordings.",
      ] },
      { id: "history", q: "Can I see songs from past nights?", a: [
        "If the host shares it, the song history is at `/history` on this site. With a singer code, your phone also shows your personal bests.",
      ] },
      { id: "privacy", q: "What does Karoulette keep about me?", a: [
        "Your display name, the songs you queued, likes and cheers, and your singer code if you have one. If you turn alerts on, it keeps your phone's alert address until you turn them off. No email, phone number or account.",
        "Everything stays on the host's own server.",
      ] },
    ],
  },
];

export const HOST_HELP = [
  {
    title: "Before the first night",
    items: [
      { id: "need", q: "What do I need?", a: [
        "- Karoulette running on your server (see the README for setup).",
        "- A computer or smart TV browser connected to the TV and sound system. Chrome or Edge work best.",
        "- That browser signed in to **YouTube Premium** for ad-free playback (optional, but ads interrupt singers).",
        "- Optional: a YouTube Data API key for faster search (`YOUTUBE_API_KEY`). Without one, a slower backup search is used.",
      ] },
      { id: "first-event", q: "How do I run my first event?", a: [
        "1. On the TV's browser, open `/host` and sign in with the host PIN.",
        "2. Type a name under **Start a new event** and tap **Create event**.",
        "3. Tick the Premium checklist and press **Continue**. This click also lets the browser play sound. Press ⛶ or F11 for full screen.",
        "4. Guests scan the QR code and add songs.",
        "5. Press **▶ Start event**. Songs play one per singer per round, each after a short “Get ready” countdown.",
        "6. When you're done, press **End event** for the recap.",
      ] },
      { id: "premium", q: "Why does the checklist ask about YouTube Premium?", a: [
        "Karoulette plays YouTube's own player and never downloads videos. A browser signed in to Premium plays them without ads. Without Premium, everything still works, with ads.",
      ] },
      { id: "pin", q: "Where's the host PIN? I forgot it", a: [
        "It's `HOST_PIN` in your `.env` file. If it was left blank, Karoulette generated one and saved it in `generated-host-pin.txt` in the data folder.",
        "Change it in Host admin → Security (unless `HOST_PIN` is set, which always wins). Changing it signs out every other screen.",
      ] },
      { id: "join-address", q: "The QR code shows the wrong address", a: [
        "Set `PUBLIC_BASE_URL` in `.env` to the address guests use, like `https://karaoke.example.ca`, then run `./update.sh`. When it's blank, the QR code uses the address the TV opened.",
      ] },
      { id: "https", q: "Do I need https?", a: [
        "On your home network, no. For guests joining over the internet, and for phone alerts (which browsers only allow on https), put Karoulette behind a Cloudflare Tunnel or a reverse proxy with a certificate. See the README's Security section.",
      ] },
    ],
  },
  {
    title: "Running the night",
    items: [
      { id: "controls", q: "Where did the TV controls go?", a: [
        "They hide after a few seconds so the TV stays clean. Move the mouse to show them, or press **H**.",
      ] },
      { id: "shortcuts", q: "Are there keyboard shortcuts?", a: [
        "- **Space**: pause or play the video",
        "- **N**: skip the song",
        "- **G**: start the song now (skip the “Get ready” countdown)",
        "- **P**: smoke break (pause or resume the queue)",
        "- **S**: re-spin the theme",
        "- **H**: show or hide the controls",
      ] },
      { id: "remote", q: "Can I control it from my phone?", a: [
        "Yes. Press **📱 Remote** on the TV and scan the code, or open **📱 Remote** beside the event on the host page. Sign in with the host PIN to skip, pause, change the volume, start a Superset and manage the queue from anywhere in the room.",
      ] },
      { id: "no-sound", q: "The video won't start or there's no sound", a: [
        "Browsers block sound until someone clicks the page. Press **▶ Play video** once, and allow autoplay with sound for this site in the browser's settings so it doesn't happen again.",
        "Also check the TV input, the sound system and the volume on the video itself (the remote's 🔉 and 🔊 buttons change it).",
      ] },
      { id: "skipped", q: "A song was skipped by itself", a: [
        "Some videos can't be played outside YouTube. Karoulette skips them and tells the singer, who can pick another song that plays straight away.",
      ] },
      { id: "queue", q: "How do I move or remove a song?", a: [
        "With the TV controls showing (or on the remote), ⤒ beside a song plays it next and ✕ removes it.",
      ] },
      { id: "order", q: "How do I change the singer order?", a: [
        "Host admin → Events → **Singer order**: ▲ and ▼ move a singer. New singers always join at the end.",
      ] },
      { id: "bouche", q: "How do I remove a disruptive guest?", a: [
        "Host admin → Events → Singer order → **Bouche!** Their queued songs go too, and the TV lets everyone know.",
      ] },
      { id: "break", q: "How do I take a break?", a: [
        "Press **🚬 Pause queue** (or **P**). The TV shows a smoke break screen, guests keep adding songs, and **▶ Resume queue** picks up where you left off.",
      ] },
      { id: "rejoin-host", q: "A guest switched phones and lost their code", a: [
        "Host admin → Events → Singer order shows each singer's **rejoin code**. They enter it with the event code on the new phone.",
      ] },
      { id: "end", q: "What happens when I end the event?", a: [
        "The queue is cleared, and the TV and phones show the recap. The TV shows a QR code for the night's playlist. Songs stay in the song history.",
        "Export a CSV from Host admin → Events, or **Archive** the event to hide it and keep its songs.",
      ] },
    ],
  },
  {
    title: "Themes, Supersets and rules",
    items: [
      { id: "host-themes", q: "How do themes work?", a: [
        "Switch them on per event in Host admin → Events. Each round then spins a theme as a suggestion. Edit the list, the search ideas guests see and how often each comes up in Host admin → Themes.",
      ] },
      { id: "host-superset", q: "How do Supersets work?", a: [
        "Everyone sings one extra song that fits a theme, in singer order, before the queue carries on. Start one with **★ Superset**, let guests call a vote (most votes wins), or set a random chance per round in the event's settings.",
        "If someone is slow to pick, **⏭ Skip** their turn. **✖ Cancel superset** ends it.",
      ] },
      { id: "rules", q: "Can I limit songs, length or content?", a: [
        "Host admin → Events has, per event:",
        "- Songs each singer can have waiting",
        "- Longest video allowed",
        "- Safe search (off, moderate or strict)",
        "- Prevent the same song twice in one night",
        "- “Get ready” countdown length",
        "- Autoplay when the first song is queued",
      ] },
      { id: "last-call", q: "How does last call work?", a: [
        "Set a closing time in the event's settings. Phones and the TV show how much room is left, and songs that would run past closing time are refused.",
      ] },
    ],
  },
  {
    title: "Admin and upkeep",
    items: [
      { id: "quota", q: "Search stopped working or got slow", a: [
        "YouTube's free quota allows about 99 new searches a day; repeated searches are free for 24 hours. Host admin → YouTube shows what's left. When it runs out, the backup search takes over until midnight Pacific time.",
      ] },
      { id: "backups", q: "How do I back up?", a: [
        "Host admin → Backups: make one, download it, or restore. Backups include the banner photo, the PIN hash and the alert signing key, so keep them somewhere safe.",
      ] },
      { id: "updates", q: "How do I update?", a: [
        "Host admin → Updates shows new releases and upgrades in one click. On the server, `./update.sh` does the same.",
      ] },
      { id: "appearance", q: "Can I change the look?", a: [
        "Host admin → Appearance: pick a colour scheme (every screen switches at once) and upload a banner photo.",
      ] },
      { id: "singer-codes-host", q: "Two people claimed the same past night", a: [
        "Host admin → Song history → **Singers and codes** lists nights to decide. Settle them there, reset a singer's code, or merge names one singer has used.",
      ] },
      { id: "share-history", q: "Who can see the song history?", a: [
        "Anyone with the address can see `/history` unless you switch sharing off in Host admin → Song history.",
      ] },
      { id: "monitor", q: "How do I know it's running?", a: [
        "`/api/health` answers `\"status\":\"ok\"` when the app and database are fine. Point Uptime Kuma or any monitor at it.",
      ] },
    ],
  },
];

/** Plain text of an entry, for search. */
export const entryText = (item) => `${item.q} ${item.a.join(" ")}`.replace(/[*`]/g, "").toLowerCase();
