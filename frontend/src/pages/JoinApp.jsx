import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api, guestSession } from "../lib/api";
import { applyScheme } from "../lib/schemes";
import { useCountdown, useEventSocket } from "../lib/useEventSocket";
import { decodeEntities, formatDuration } from "../lib/format";
import ThemeSpinner from "../components/ThemeSpinner";
import Recap from "../components/Recap";
import { SupersetChooser, SupersetLineup } from "../components/Superset";
import { Toasts, useToasts } from "../components/Toasts";
import { formatWait, secondsUntil, singers, sings } from "../lib/eta";
import { alertsSupported, notify, useInstall } from "../lib/pwa";

function JoinForm({ initialCode, onJoined }) {
  const [code, setCode] = useState((initialCode || "").toUpperCase());
  const [name, setName] = useState("");
  const [rejoin, setRejoin] = useState(false);
  const [rejoinCode, setRejoinCode] = useState("");
  const [eventName, setEventName] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    setEventName("");
    if (code.length < 5) return;
    api(`/api/public/events/${encodeURIComponent(code)}`)
      .then((ev) => setEventName(ev.status === "ended" ? "" : ev.name))
      .catch(() => {});
  }, [code]);

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const res = rejoin
        ? await api("/api/guest/rejoin", { method: "POST", body: { code: code.trim(), rejoin_code: rejoinCode.trim() } })
        : await api("/api/guest/join", { method: "POST", body: { code: code.trim(), name: name.trim() } });
      guestSession.save(res.token, res.event.join_code);
      onJoined(res);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <main className="phone center-page">
      <form className="card narrow" onSubmit={submit}>
        <h1 className="brand small">Kar<span>oulette</span></h1>
        {eventName ? <h2>Join {eventName}</h2> : <h2>Join the party</h2>}
        <label className="field">
          <span>Event code</span>
          <input value={code} onChange={(e) => setCode(e.target.value.toUpperCase().replace(/[^A-Z0-9]/g, ""))}
                 maxLength={10} autoCapitalize="characters" autoComplete="off" required placeholder="ABCDE" />
        </label>
        {rejoin ? (
          <label className="field">
            <span>Your rejoin code</span>
            <input value={rejoinCode} maxLength={6} required autoFocus autoCapitalize="characters" autoComplete="off"
                   onChange={(e) => setRejoinCode(e.target.value.toUpperCase().replace(/[^A-Z0-9]/g, ""))}
                   placeholder="6 letters and numbers" className="code-input" />
          </label>
        ) : (
          <label className="field">
            <span>Your display name</span>
            <input value={name} onChange={(e) => setName(e.target.value)} maxLength={24} required autoFocus={!!code}
                   placeholder="What should the TV call you?" autoComplete="nickname" />
          </label>
        )}
        {error && <p className="error">{error}</p>}
        {rejoin ? (
          <button className="btn btn-primary btn-block btn-xl" disabled={busy || rejoinCode.length !== 6 || !code}>Rejoin</button>
        ) : (
          <button className="btn btn-primary btn-block btn-xl" disabled={busy || !name.trim() || !code}>Join the rotation</button>
        )}
        <p className="muted small">{rejoin
          ? "Your code is at the bottom of your old phone's screen, or ask the host: it's in Host admin."
          : "No account needed. You'll sing in the order people joined."}</p>
        <button type="button" className="btn btn-link btn-block" onClick={() => { setRejoin(!rejoin); setError(""); }}>
          {rejoin ? "New here? Join with your name" : "Switched phones? Rejoin with your code"}
        </button>
      </form>
    </main>
  );
}

function SearchPanel({ canAdd, limitNote, onAdd, push, setPick, partners }) {
  const [q, setQ] = useState("");
  const [duet, setDuet] = useState("");
  const [results, setResults] = useState(null);
  const [busy, setBusy] = useState(false);
  const [adding, setAdding] = useState(null);
  const [note, setNote] = useState("");

  const search = async (e) => {
    e.preventDefault();
    if (!q.trim()) return;
    setBusy(true);
    setNote("");
    try {
      const res = await api(`/api/guest/search?q=${encodeURIComponent(q.trim())}`, { guest: true });
      setResults(res.results);
      if (res.warning) setNote(res.warning);
      else if (res.source === "ytdlp") setNote("Using backup search. Durations may be missing.");
    } catch (err) {
      push(err.message, "error");
    } finally {
      setBusy(false);
    }
  };

  const add = async (r) => {
    setAdding(r.video_id);
    try {
      await onAdd(r, duet ? Number(duet) : null);
      setResults(null);
      setQ("");
      setDuet("");
    } catch (err) {
      push(err.message, "error");
    } finally {
      setAdding(null);
    }
  };

  return (
    <section className="card">
      <form className="search" onSubmit={search} role="search">
        <input type="search" value={q} onChange={(e) => setQ(e.target.value)} maxLength={100}
               placeholder="Song or artist" enterKeyHint="search" />
        <button className="btn btn-primary" disabled={busy || !q.trim()}>{busy ? "…" : "Search"}</button>
      </form>
      {setPick && <p className="set-pick-note">★ Your next pick is your <strong>Superset song</strong>: it must fit
        “{setPick}”, or others can flag it!</p>}
      <p className="muted small">We add “karaoke” to your search for you.</p>
      {partners.length > 0 && (
        <label className="duet-pick">
          <span>Sing it</span>
          <select value={duet} onChange={(e) => setDuet(e.target.value)}>
            <option value="">Solo</option>
            {partners.map((g) => <option key={g.id} value={g.id}>As a duet with {g.name}</option>)}
          </select>
        </label>
      )}
      {limitNote && <p className="warning small">{limitNote}</p>}
      {note && <p className="warning small">{note}</p>}
      {results && !results.length && <p className="muted">No karaoke versions found. Try different words.</p>}
      {results && (
        <ul className="results">
          {results.map((r) => (
            <li key={r.video_id} className="result">
              <img src={r.thumbnail || `https://i.ytimg.com/vi/${r.video_id}/mqdefault.jpg`} alt="" loading="lazy" />
              <div className="r-text">
                <div className="r-title">{decodeEntities(r.title)}</div>
                <div className="r-meta">{decodeEntities(r.channel)}{r.duration_s ? ` · ${formatDuration(r.duration_s)}` : ""}</div>
              </div>
              <button className={`btn ${setPick ? "btn-gold" : "btn-primary"}`} disabled={(!canAdd && !setPick) || adding === r.video_id}
                      onClick={() => add(r)}>
                {adding === r.video_id ? "…" : setPick ? "★ Add" : "Add"}
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function ReactionBar({ emojis, push }) {
  const last = useRef(0);
  const [popped, setPopped] = useState(null);
  const send = async (emoji) => {
    const now = Date.now();
    if (now - last.current < 350) return;
    last.current = now;
    setPopped(emoji + now);
    try { await api("/api/guest/react", { method: "POST", guest: true, body: { emoji } }); }
    catch (e) { if (e.status === 429) push("Easy there! Give the cheers a second.", "info", 2500); }
  };
  return (
    <div className="reaction-bar" role="group" aria-label="Cheer for the singer">
      {emojis.map((e) => (
        // A new key on each tap restarts the pop animation.
        <button key={popped?.startsWith(e) ? popped : e} className={`reaction-btn ${popped?.startsWith(e) ? "popped" : ""}`}
                onClick={() => send(e)} aria-label={`Send ${e}`}>{e}</button>
      ))}
    </div>
  );
}

/** A Superset called by a singer: everyone else votes yes or no, and the majority wins. */
function VoteCard({ vote, myId, serverNow, push }) {
  const left = useCountdown(vote.ends_at, serverNow, 0);
  const mine = vote.called_by === myId;
  const voted = vote.voters.includes(myId);
  const cast = async (yes) => {
    try { await api("/api/guest/superset/vote", { method: "POST", guest: true, body: { yes } }); }
    catch (e) { push(e.message, "error"); }
  };
  return (
    <section className="card vote-card" aria-live="polite">
      <div className="label">★ Superset vote · {Math.ceil(left)} s left</div>
      <p className="vote-question">{mine ? "You called a Superset" : `${vote.called_by_name} calls a Superset`}
        {vote.mode === "now" && vote.song ? <>, kicked off by “{decodeEntities(vote.song)}”</> : " after this song"}</p>
      <p className="muted small">If most say yes, everyone picks one extra song that fits
        {vote.mode === "now" && vote.song ? " (songs like that one)" : " a theme we spin"}, and we go round in singer order.</p>
      {!mine && (
        <div className="vote-buttons">
          <button className="btn btn-gold btn-xl" onClick={() => cast(true)}>👍 Yes!</button>
          <button className="btn btn-xl" onClick={() => cast(false)}>👎 No</button>
        </div>
      )}
      <p className="vote-tally">Yes {vote.yes} · No {vote.no} · {vote.yes + vote.no} of {vote.eligible} voted
        {voted ? " · you've voted (tap again to change)" : mine ? " · waiting for votes…" : ""}</p>
    </section>
  );
}

function GuestHome({ me, onLeave }) {
  const { toasts, push } = useToasts();
  const [tab, setTab] = useState("me");
  const [spinMeta, setSpinMeta] = useState({ candidates: [] });
  const [themes, setThemes] = useState([]);
  const [alerts, setAlerts] = useState(() => alertsSupported() && Notification.permission === "granted");
  const { canInstall, install, iosHint } = useInstall();
  const prevIdx = useRef(null);
  const [choosing, setChoosing] = useState(false);
  const myId = me.guest.id;

  useEffect(() => { api("/api/public/themes").then(setThemes).catch(() => {}); }, []);

  const onMessage = useCallback((msg) => {
    const d = msg.data || {};
    if (msg.for_guest_id && msg.for_guest_id !== myId) return;
    switch (msg.type) {
      case "notice": push(d.text, d.level); break;
      case "theme_spun": setSpinMeta({ candidates: d.candidates }); break;
      case "song_error": push(`Your song “${decodeEntities(d.title)}” couldn't play. Pick another and it plays straight away!`, "warning", 9000); break;
      case "you_are_singing":
        push("🎤 You're up! Grab the mic.", "success", 9000);
        navigator.vibrate?.([200, 100, 200]);
        notify("🎤 You're up!", `Grab the mic: ${decodeEntities(d.title)}`);
        break;
      case "you_are_next":
        push("You're up next on the mic. Get ready!", "info", 8000);
        navigator.vibrate?.([300, 150, 300]);
        notify("You're up next!", `Head to the mic: ${decodeEntities(d.title)} is next.`);
        break;
      case "duet_invite": push(`🎶 ${d.name} added you to a duet: “${decodeEntities(d.title)}”`, "success", 9000); break;
      case "session_replaced":
        window.alert("You signed in on another phone, so this one has been signed out.");
        onLeave();
        break;
      case "superset":
        if (d.active) navigator.vibrate?.([100, 60, 100, 60, 100]); // the notice says what it is
        break;
      case "superset_your_turn":
        push(`★ It's your Superset turn! Pick a song that fits ${d.theme}. Everyone's waiting.`, "gold", 10000);
        navigator.vibrate?.([300, 150, 300, 150, 300]);
        notify("★ Your Superset turn!", `Pick a song that fits ${d.theme}.`);
        break;
      case "guest_left":
        if (d.guest_id === myId && d.reason === "removed") {
          window.alert("🥖 You've been BOUCHED! The host removed you from this event.");
          onLeave();
        }
        break;
      default: break;
    }
  }, [myId, push, onLeave]);

  const { state, connected, serverNow } = useEventSocket(me.event.join_code, {
    token: guestSession.token, onMessage, onAuthError: onLeave,
  });
  useEffect(() => { if (state?.appearance) applyScheme(state.appearance.scheme); }, [state?.appearance?.scheme]);
  const round = state?.round;
  const spinLeft = useCountdown(round?.spun_at ? round.spun_at + round.spin_seconds : null, serverNow, 0);
  const readyLeft = useCountdown(state?.now_playing?.starts_at || null, serverNow, 0);
  const sup = state?.superset;
  const setSpinLeft = useCountdown(sup?.spun_at ? sup.spun_at + sup.spin_seconds : null, serverNow, 0);

  const addSong = async (r, duetId) => {
    const forSet = state?.superset?.slots.find((s) => s.guest_id === myId)?.status === "pending";
    await api("/api/guest/queue", { method: "POST", guest: true,
      body: { video_id: r.video_id, title: r.title, channel: r.channel, thumbnail: r.thumbnail, duet_guest_id: duetId } });
    push(forSet ? "★ That's your Superset song!" : duetId ? "Duet added! 🎶 Your partner gets a heads-up."
      : "Song added! 🎶 Add as many as you like.", "success");
  };

  const callSuperset = async (mode) => {
    setChoosing(false);
    try { await api("/api/guest/superset/call", { method: "POST", guest: true, body: { mode } }); }
    catch (e) { push(e.message, "error"); }
  };

  const flag = async (itemId) => {
    try { await api(`/api/guest/flag/${itemId}`, { method: "POST", guest: true }); push("Flag sent to the host.", "info"); }
    catch (e) { push(e.message, "error"); }
  };

  const turnOnAlerts = async () => {
    try {
      const result = await Notification.requestPermission();
      setAlerts(result === "granted");
      push(result === "granted" ? "🔔 Alerts on. We'll buzz you when you're nearly up." : "Alerts are blocked in your browser settings.",
        result === "granted" ? "success" : "warning");
    } catch { /* unsupported */ }
  };

  // Heads-up when two songs stand between you and the mic (the server sends "up next" itself).
  const firstMine = state ? state.queue.findIndex((i) => sings(i, myId)) : -1;
  useEffect(() => {
    if (!state) return;
    const prev = prevIdx.current;
    prevIdx.current = firstMine;
    if (firstMine === 1 && prev !== null && prev > 1) {
      push("⏳ Nearly your turn: two songs to go. Head towards the mic!", "info", 9000);
      navigator.vibrate?.([150, 100, 150]);
      notify("Nearly your turn!", "Two songs to go. Head towards the mic.");
    }
  }, [firstMine, state, push]);

  const songAction = async (path, opts = {}) => {
    try { await api(path, { method: "POST", guest: true, ...opts }); } catch (e) { push(e.message, "error"); }
  };

  const leave = async () => {
    if (!window.confirm("Leave this event? Your queued songs will be removed.")) return;
    try { await api("/api/guest/leave", { method: "POST", guest: true }); } catch { /* already gone */ }
    onLeave();
  };

  if (!state) return <main className="phone center-page"><p className="muted">Connecting…</p></main>;

  const ev = state.event;
  const superset = !!sup;
  const mySlot = sup?.slots.find((s) => s.guest_id === myId);
  const myTurnWaiting = sup?.waiting_for === myId;
  const setSpinning = !!sup?.spun_at && setSpinLeft > 0;
  const spinning = !!round.spun_at && spinLeft > 0;
  const mySongs = state.queue.filter((i) => i.guest_id === myId);
  const myDuets = state.queue.filter((i) => i.duet_guest_id === myId);
  const singingNow = sings(state.now_playing, myId);
  const firstIdx = firstMine;
  const me_ = state.guests.find((g) => g.id === myId);
  const now = serverNow() / 1000;
  const gettingReady = singingNow && readyLeft > 0;
  const cap = Number(ev.config.max_songs_per_singer) || 0;
  const atCap = cap > 0 && mySongs.length >= cap;
  const wait = (idx) => formatWait(secondsUntil(state, idx, now));

  let headline;
  let sub = null;
  if (ev.status === "ended") { headline = "Thanks for singing!"; sub = "This event has ended."; }
  else if (myTurnWaiting) { headline = "★ Your Superset turn!"; sub = `Pick a song that fits ${sup.theme}. Everyone's waiting!`; }
  else if (gettingReady) { headline = "🎤 You're up! Grab the mic"; sub = `Your song starts in ${Math.ceil(readyLeft)} s.`; }
  else if (singingNow) headline = "🎤 You're singing now!";
  else if (firstIdx === 0) { headline = "Your song is up next!"; sub = `About ${wait(0).replace("≈ ", "")} to go. Get ready!`; }
  else if (firstIdx > 0) { headline = `${firstIdx} song${firstIdx === 1 ? "" : "s"} before yours`; sub = `You're on in ${wait(firstIdx)}.`; }
  else { headline = "Pick a song!"; sub = me_?.new_singer ? "Welcome, new singer! You're at the end of the singer order: your first song plays at the end of this round." : "Add as many as you like. They play in singer order, one per round."; }
  if (ev.status === "draft") sub = "The host hasn't started yet, but you can add songs now.";
  const partners = state.guests.filter((g) => g.id !== myId);
  const vote = state.superset_vote;
  const canCall = ev.status === "active" && round.number > 0 && !superset && !vote
    && !(state.vote_callers || []).includes(myId) && partners.length > 0;
  const slotText = {
    pending: "Pick a song that fits: your next pick is your Superset song. It's a bonus; your other songs keep their places.",
    picked: `Your Superset song: “${decodeEntities(mySlot?.title || "")}”. You'll sing it in singer order.`,
    singing: "You're on! 🎤",
    sung: "Done! Nice one. ✓",
    passed: "You're sitting this one out.",
    skipped: "Your turn was skipped.",
  };
  if (ev.paused && ev.status === "active") sub = "🚬 Smoke break! The music's on hold. Keep adding songs.";

  return (
    <div className={`phone ${superset ? "is-superset" : ""}`}>
      <header className="phone-top">
        <div>
          <div className="brand tiny">Kar<span>oulette</span></div>
          <div className="phone-event">{ev.name}</div>
        </div>
        <div className="phone-me">
          <span>{me.guest.name}</span>
          {!connected && <span className="error-tag small">Reconnecting…</span>}
        </div>
      </header>

      {sup && (
        <section className={`card set-card ${myTurnWaiting ? "my-turn" : ""}`}>
          <div className="label">★ Superset · everyone sings</div>
          {setSpinning ? (
            <ThemeSpinner spinKey={`set-${sup.id}-${sup.spun_at}`} candidates={spinMeta.candidates?.length ? spinMeta.candidates : themes}
                          result={sup.theme} duration={sup.spin_seconds} superset size="md" />
          ) : <div className="theme-pill superset">{sup.theme}</div>}
          {sup.inspired_by && <div className="muted small">Kicked off by “{decodeEntities(sup.inspired_by)}”</div>}
          {mySlot && <p className={`set-me ${myTurnWaiting ? "pulse" : ""}`}>{myTurnWaiting ? "★ It's your turn! Pick now: everyone's waiting." : slotText[mySlot.status]}</p>}
          {mySlot && ["pending", "picked"].includes(mySlot.status) && (
            <div className="set-actions">
              {mySlot.status === "picked" && (
                <button className="btn" onClick={() => window.confirm("Pick a different Superset song?") &&
                  songAction(`/api/guest/queue/${mySlot.item_id}`, { method: "DELETE" })}>Change my pick</button>
              )}
              <button className="btn btn-link" onClick={() => window.confirm("Sit this Superset out?") &&
                songAction("/api/guest/superset/pass")}>Sit this one out</button>
            </div>
          )}
          <SupersetLineup superset={sup} myId={myId} onFlag={flag} />
        </section>
      )}
      {ev.paused && ev.status === "active" && <div className="smoke-banner">🚬 Smoke break! Back in a few.</div>}
      {vote && <VoteCard vote={vote} myId={myId} serverNow={serverNow} push={push} />}

      <nav className="tabs phone-tabs">
        <button className={`tab ${tab === "me" ? "active" : ""}`} onClick={() => setTab("me")}>My songs ({mySongs.length})</button>
        <button className={`tab ${tab === "queue" ? "active" : ""}`} onClick={() => setTab("queue")}>Queue ({state.queue.length})</button>
      </nav>

      {tab === "me" && (
        <>
          <div className={`status-card ${firstIdx === 0 || singingNow ? "your-turn" : ""} ${superset ? "superset" : ""}`}>
            <div className={`status-big ${firstIdx === 0 || gettingReady ? "pulse" : ""}`}>{headline}</div>
            {sub && <div className="muted">{sub}</div>}
            {ev.status !== "ended" && alertsSupported() && !alerts && (
              <button className="btn btn-link small" onClick={turnOnAlerts}>🔔 Buzz me when I'm nearly up</button>
            )}
            {canCall && (
              <button className="btn btn-gold call-superset" onClick={() => setChoosing(true)}>★ Call a Superset</button>
            )}
            {round.number > 0 && ev.status !== "ended" && (round.theme || spinning) && (
              <div className="round-theme">
                <div className="label">Round {round.number} theme</div>
                {spinning ? (
                  <ThemeSpinner spinKey={`${round.number}-${round.spun_at}`} candidates={spinMeta.candidates?.length ? spinMeta.candidates : themes}
                                result={round.theme?.name} duration={round.spin_seconds} size="md" />
                ) : round.theme && (
                  <>
                    <div className="theme-pill">{round.theme.name}</div>
                    {round.theme.description && <div className="muted small">{round.theme.description}</div>}
                    <div className="muted small">Just a suggestion: sing what you like!</div>
                  </>
                )}
              </div>
            )}
          </div>

          {ev.status === "ended" && state.recap && (
            <section className="card"><Recap recap={state.recap} eventName={ev.name} me={me.guest.name} size="phone" /></section>
          )}

          {ev.status !== "ended" && <SearchPanel canAdd={!atCap} onAdd={addSong} push={push}
                                                 setPick={mySlot?.status === "pending" ? sup.theme : null}
                                                 partners={partners}
                                                 limitNote={atCap ? `You have ${mySongs.length} songs waiting, the most the host allows. Add another once one has played.` : ""} />}

          {mySongs.length > 0 && (
            <section className="card">
              <h3>Your songs</h3>
              <ul className="results">
                {mySongs.map((i, n) => {
                  const pos = state.queue.indexOf(i);
                  return (
                    <li key={i.id} className="result mine-song">
                      <div className="r-text">
                        <div className="r-title">{decodeEntities(i.title)}</div>
                        <div className="r-meta">{pos === 0 ? "Up next" : `#${pos + 1} in the queue`}{i.round ? ` · round ${i.round}` : ""}
                          {` · ${wait(pos)}`}{i.duet_name ? ` · duet with ${i.duet_name}` : ""}</div>
                        {pos === 0 && state.queue.length > 1 && (
                          <button className="btn btn-block pass-btn" onClick={() =>
                            window.confirm("Let the next singer go first? Your song plays right after theirs.") &&
                            songAction(`/api/guest/queue/${i.id}/let-next-go-first`)}>
                            Not ready? Let the next singer go first
                          </button>
                        )}
                      </div>
                      <div className="song-actions">
                        <button className="btn" title="Sing this one sooner" disabled={n === 0}
                                onClick={() => songAction(`/api/guest/queue/${i.id}/up`)}>▲</button>
                        <button className="btn btn-danger" title="Remove" onClick={() =>
                          window.confirm("Remove this song from the queue?") &&
                          songAction(`/api/guest/queue/${i.id}`, { method: "DELETE" })}>✕</button>
                      </div>
                    </li>
                  );
                })}
              </ul>
            </section>
          )}

          {myDuets.length > 0 && (
            <section className="card">
              <h3>Duets you're in</h3>
              <ul className="results">
                {myDuets.map((i) => {
                  const pos = state.queue.indexOf(i);
                  return (
                    <li key={i.id} className="result mine-song">
                      <div className="r-text">
                        <div className="r-title">{decodeEntities(i.title)}</div>
                        <div className="r-meta">With {i.guest_name} · {pos === 0 ? "Up next" : `#${pos + 1} in the queue`} · {wait(pos)}</div>
                      </div>
                      <div className="song-actions">
                        <button className="btn btn-danger" title="Step out of this duet" onClick={() =>
                          window.confirm(`Step out of this duet? ${i.guest_name} keeps the song.`) &&
                          songAction(`/api/guest/queue/${i.id}/leave-duet`)}>✕</button>
                      </div>
                    </li>
                  );
                })}
              </ul>
            </section>
          )}
        </>
      )}

      {tab === "queue" && (
        <section className="card">
          {state.now_playing && (
            <div className="now-mini">
              <div className="label">Now singing</div>
              <strong>{singers(state.now_playing)}</strong> · {decodeEntities(state.now_playing.title)}
            </div>
          )}
          {sup && (
            <>
              <h3>★ Superset first: {sup.theme}</h3>
              <SupersetLineup superset={sup} myId={myId} onFlag={flag} />
              <h3>Then the queue</h3>
            </>
          )}
          {!state.queue.length && <p className="muted">The queue is empty.</p>}
          <ol className="results">
            {state.queue.map((i) => (
              <li key={i.id} className={`result ${sings(i, myId) ? "mine" : ""}`}>
                <img src={i.thumbnail} alt="" loading="lazy" />
                <div className="r-text">
                  <div className="r-title">{decodeEntities(i.title)}</div>
                  <div className="r-meta">{singers(i)}{i.duration_s ? ` · ${formatDuration(i.duration_s)}` : ""}
                    {i.flags > 0 ? ` · ⚑ ${i.flags}` : ""}</div>
                </div>
                {i.is_superset && i.guest_id !== myId && (
                  <button className="btn" title="Flag as off-theme" onClick={() => flag(i.id)}>⚑</button>
                )}
              </li>
            ))}
          </ol>
          <h3>Singer order</h3>
          <ol className="list compact">
            {state.guests.map((g) => (
              <li key={g.id} className={g.id === myId ? "mine" : ""}>
                {g.name}{g.id === myId ? " (you)" : ""}{g.new_singer && <span className="new-tag">New</span>}
                <span className="muted small"> · {g.queued} song{g.queued === 1 ? "" : "s"} queued</span>
              </li>
            ))}
          </ol>
        </section>
      )}

      <footer className="phone-footer">
        {me.guest.rejoin_code && ev.status !== "ended" && (
          <p className="rejoin-note small">Your rejoin code: <strong className="rejoin-code">{me.guest.rejoin_code}</strong>
            <br /><span className="muted">Switching phones? Use it with the event code to keep your place and songs.</span></p>
        )}
        {canInstall && <button className="btn" onClick={install}>📲 Install Karoulette</button>}
        {iosHint && <p className="muted small">Tip: tap Share, then “Add to Home Screen” to keep Karoulette one tap away.</p>}
        <button className="btn btn-link" onClick={leave}>Leave event</button>
      </footer>
      {state.now_playing && ev.status === "active" && <ReactionBar emojis={state.reactions || []} push={push} />}
      {choosing && (
        <SupersetChooser nowPlaying={state.now_playing} onClose={() => setChoosing(false)} onChoose={callSuperset}
                         note="Everyone else votes; if most say yes, it's on." />
      )}
      <Toasts toasts={toasts} />
    </div>
  );
}

export default function JoinApp() {
  const { code } = useParams();
  const navigate = useNavigate();
  const [me, setMe] = useState(null);
  const [checking, setChecking] = useState(!!guestSession.token);

  useEffect(() => {
    if (!guestSession.token) return;
    api("/api/guest/me", { guest: true })
      .then((res) => {
        // Scanning a different event's QR code starts a fresh session.
        if (code && res.event.join_code !== code.toUpperCase()) { guestSession.clear(); setMe(null); }
        else if (res.event.status === "ended") { guestSession.clear(); setMe(null); }
        else setMe(res);
      })
      .catch(() => guestSession.clear())
      .finally(() => setChecking(false));
  }, [code]);

  const leave = useCallback(() => {
    guestSession.clear();
    setMe(null);
    navigate(code ? `/join/${code}` : "/join");
  }, [code, navigate]);

  if (checking) return <main className="phone center-page"><p className="muted">Loading…</p></main>;
  if (!me) return <JoinForm initialCode={code || guestSession.code || ""} onJoined={setMe} />;
  return <GuestHome me={me} onLeave={leave} />;
}
