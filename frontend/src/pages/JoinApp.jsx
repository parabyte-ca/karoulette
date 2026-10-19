import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api, guestSession } from "../lib/api";
import { applyScheme } from "../lib/schemes";
import { useEventSocket } from "../lib/useEventSocket";
import { decodeEntities, formatDuration } from "../lib/format";
import ThemeSpinner from "../components/ThemeSpinner";
import Countdown from "../components/Countdown";
import { Toasts, useToasts } from "../components/Toasts";

function JoinForm({ initialCode, onJoined }) {
  const [code, setCode] = useState((initialCode || "").toUpperCase());
  const [name, setName] = useState("");
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
      const res = await api("/api/guest/join", { method: "POST", body: { code: code.trim(), name: name.trim() } });
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
        <h1 className="brand small">Karaoke<span>Queue</span></h1>
        {eventName ? <h2>Join {eventName}</h2> : <h2>Join the party</h2>}
        <label className="field">
          <span>Event code</span>
          <input value={code} onChange={(e) => setCode(e.target.value.toUpperCase().replace(/[^A-Z0-9]/g, ""))}
                 maxLength={10} autoCapitalize="characters" autoComplete="off" required placeholder="ABCDE" />
        </label>
        <label className="field">
          <span>Your display name</span>
          <input value={name} onChange={(e) => setName(e.target.value)} maxLength={24} required autoFocus={!!code}
                 placeholder="What should the TV call you?" autoComplete="nickname" />
        </label>
        {error && <p className="error">{error}</p>}
        <button className="btn btn-primary btn-block btn-xl" disabled={busy || !name.trim() || !code}>Join the rotation</button>
        <p className="muted small">No account needed. You'll sing in the order people joined.</p>
      </form>
    </main>
  );
}

function SearchPanel({ canAdd, onAdd, push, superset, theme }) {
  const [q, setQ] = useState("");
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
      await onAdd(r);
      setResults(null);
      setQ("");
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
               placeholder={theme ? `Song or artist (${theme})` : "Song or artist"} enterKeyHint="search" />
        <button className="btn btn-primary" disabled={busy || !q.trim()}>{busy ? "…" : "Search"}</button>
      </form>
      <p className="muted small">We add “karaoke” to your search for you.
        {superset && " Superset round: your pick must fit the theme, or others can flag it!"}</p>
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
              <button className="btn btn-primary" disabled={!canAdd || adding === r.video_id} onClick={() => add(r)}>
                {adding === r.video_id ? "…" : "Add"}
              </button>
            </li>
          ))}
        </ul>
      )}
      {results && !canAdd && <p className="muted small">You can add a song when it's your turn.</p>}
    </section>
  );
}

function GuestHome({ me, onLeave }) {
  const { toasts, push } = useToasts();
  const [tab, setTab] = useState("me");
  const [spinMeta, setSpinMeta] = useState({ duration: 5, candidates: [] });
  const [themes, setThemes] = useState([]);
  const lastTurnId = useRef(null);
  const myId = me.guest.id;

  useEffect(() => { api("/api/public/themes").then(setThemes).catch(() => {}); }, []);

  const onMessage = useCallback((msg) => {
    const d = msg.data || {};
    if (msg.for_guest_id && msg.for_guest_id !== myId) return;
    switch (msg.type) {
      case "notice": push(d.text, d.level); break;
      case "theme_spun": setSpinMeta({ duration: d.duration, candidates: d.candidates }); break;
      case "song_error": push(`Your song “${decodeEntities(d.title)}” couldn't play. You get to pick again!`, "warning", 9000); break;
      case "you_are_singing": push("🎤 You're singing now! Grab the mic.", "success", 9000); navigator.vibrate?.([200, 100, 200]); break;
      case "you_are_next": push("You're up next on the mic. Get ready!", "info", 8000); break;
      case "turn_overtime": push("Time's up, but your turn isn't lost. Pick a song or let the next singer go first.", "warning", 9000); break;
      case "superset": if (d.active) push(`★ SUPERSET round! Everyone sings: ${d.theme?.name}`, "gold", 9000); break;
      case "event_ended": push("The event has ended. Thanks for singing!", "info", 10000); break;
      case "guest_left":
        if (d.guest_id === myId && d.reason === "removed") {
          window.alert("The host removed you from this event.");
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

  const turn = state?.turn;
  const myTurn = turn?.guest_id === myId;

  useEffect(() => {
    if (myTurn && turn.id !== lastTurnId.current) {
      lastTurnId.current = turn.id;
      navigator.vibrate?.([300, 150, 300]);
      setTab("me");
    }
  }, [myTurn, turn?.id]);

  const position = useMemo(() => {
    if (!state) return null;
    const idx = state.upcoming.indexOf(myId);
    return idx === -1 ? null : idx + 1;
  }, [state, myId]);

  const addSong = async (r) => {
    await api("/api/guest/queue", { method: "POST", guest: true,
      body: { video_id: r.video_id, title: r.title, channel: r.channel, thumbnail: r.thumbnail } });
    push("Song added! 🎶", "success");
  };

  const leave = async () => {
    if (!window.confirm("Leave this event? Your queued songs will be removed.")) return;
    try { await api("/api/guest/leave", { method: "POST", guest: true }); } catch { /* already gone */ }
    onLeave();
  };

  if (!state) return <main className="phone center-page"><p className="muted">Connecting…</p></main>;

  const ev = state.event;
  const superset = state.round.is_superset;
  const mySongs = state.queue.filter((i) => i.guest_id === myId);
  const singingNow = state.now_playing?.guest_id === myId;
  const nextUp = state.queue[0]?.guest_id === myId;
  const choosing = myTurn && (turn.state === "choosing" || turn.state === "overtime");
  const canAdd = myTurn && (choosing || turn.state === "spinning") && ev.status === "active";
  const iPassed = (state.passed || []).some((p) => p.guest_id === myId && !p.ready);
  const passTurn = async () => {
    if (!window.confirm("Let the next singer go first? You'll pick right after them.")) return;
    try { await api("/api/guest/pass", { method: "POST", guest: true }); }
    catch (e) { push(e.message, "error"); }
  };

  let status;
  if (ev.status === "ended") status = <div className="status-card"><div className="status-big">Thanks for singing!</div><div className="muted">This event has ended.</div></div>;
  else if (myTurn) {
    status = (
      <div className={`status-card your-turn ${superset ? "superset" : ""}`}>
        <div className="status-big pulse">{turn.is_bonus ? "Pick again!" : "Your turn!"}</div>
        {turn.state === "announcing" && <div className="muted">Get ready… spinning your theme</div>}
        {turn.state === "spinning" && (
          <ThemeSpinner spinKey={`${turn.id}-${turn.theme?.name}`} candidates={spinMeta.candidates?.length ? spinMeta.candidates : themes}
                        result={turn.theme?.name} duration={spinMeta.duration} superset={superset} size="md" />
        )}
        {choosing && (
          <>
            {turn.theme && <div className={`theme-pill ${superset ? "superset" : ""}`}>{turn.theme.name}</div>}
            {turn.theme?.description && <div className="muted small">{turn.theme.description}</div>}
            {turn.state === "choosing" ? (
              <>
                <Countdown deadline={turn.deadline} remaining={turn.remaining} serverNow={serverNow}
                           total={ev.config.turn_seconds} paused={ev.rotation_paused} />
                <div className="muted small">Search below and tap Add. No rush: your turn won't be skipped.</div>
              </>
            ) : (
              <div className="overtime">⏱ Time's up, but it's still your pick.</div>
            )}
            <button className="btn btn-block pass-btn" onClick={passTurn}>Not ready? Let the next singer go first</button>
          </>
        )}
      </div>
    );
  } else {
    status = (
      <div className="status-card">
        {singingNow && <div className="status-big">🎤 You're singing now!</div>}
        {!singingNow && nextUp && <div className="status-big">Your song is up next!</div>}
        {!singingNow && !nextUp && (
          <div className="status-big">
            {position === 1 ? "You pick next" : position ? `${position} turns until you pick` : "Hang tight"}
          </div>
        )}
        {iPassed && <div className="muted">You passed. You'll pick right after the next singer.</div>}
        {turn && <div className="muted">{turn.guest_name} is {turn.state === "choosing" || turn.state === "overtime" ? "choosing a song" : "up"}.</div>}
        {ev.status !== "active" && <div className="muted">Waiting for the host to start.</div>}
        {ev.rotation_paused && <div className="muted">The host paused the rotation.</div>}
      </div>
    );
  }

  return (
    <div className={`phone ${superset ? "is-superset" : ""}`}>
      <header className="phone-top">
        <div>
          <div className="brand tiny">Karaoke<span>Queue</span></div>
          <div className="phone-event">{ev.name}</div>
        </div>
        <div className="phone-me">
          <span>{me.guest.name}</span>
          {!connected && <span className="error-tag small">Reconnecting…</span>}
        </div>
      </header>

      {superset && (
        <div className="superset-banner">★ SUPERSET ROUND · Everyone sings: <strong>{state.round.theme?.name}</strong></div>
      )}

      <nav className="tabs phone-tabs">
        <button className={`tab ${tab === "me" ? "active" : ""}`} onClick={() => setTab("me")}>My turn</button>
        <button className={`tab ${tab === "queue" ? "active" : ""}`} onClick={() => setTab("queue")}>Queue ({state.queue.length})</button>
      </nav>

      {tab === "me" && (
        <>
          {status}
          {!myTurn && turn?.theme && !superset && turn.state !== "announcing" && (
            <p className="muted center small">Current theme: <strong>{turn.theme.name}</strong></p>
          )}
          {ev.status !== "ended" && <SearchPanel canAdd={canAdd} onAdd={addSong} push={push} superset={superset}
                                                 theme={myTurn ? turn.theme?.name : null} />}
          {mySongs.length > 0 && (
            <section className="card">
              <h3>Your songs</h3>
              <ul className="results">
                {mySongs.map((i) => (
                  <li key={i.id} className="result">
                    <div className="r-text"><div className="r-title">{decodeEntities(i.title)}</div>
                      <div className="r-meta">#{state.queue.indexOf(i) + 1} in the queue</div></div>
                    <button className="btn btn-danger" onClick={async () => {
                      if (!window.confirm("Remove this song from the queue?")) return;
                      try { await api(`/api/guest/queue/${i.id}`, { method: "DELETE", guest: true }); } catch (e) { push(e.message, "error"); }
                    }}>Remove</button>
                  </li>
                ))}
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
              <strong>{state.now_playing.guest_name}</strong> · {decodeEntities(state.now_playing.title)}
            </div>
          )}
          {!state.queue.length && <p className="muted">The queue is empty.</p>}
          <ol className="results">
            {state.queue.map((i) => (
              <li key={i.id} className={`result ${i.guest_id === myId ? "mine" : ""}`}>
                <img src={i.thumbnail} alt="" loading="lazy" />
                <div className="r-text">
                  <div className="r-title">{decodeEntities(i.title)}</div>
                  <div className="r-meta">{i.guest_name}{i.duration_s ? ` · ${formatDuration(i.duration_s)}` : ""}
                    {i.is_superset && i.theme ? ` · ${i.theme}` : ""}{i.flags > 0 ? ` · ⚑ ${i.flags}` : ""}</div>
                </div>
                {i.is_superset && i.guest_id !== myId && (
                  <button className="btn" title="Flag as off-theme" onClick={async () => {
                    try { await api(`/api/guest/flag/${i.id}`, { method: "POST", guest: true }); push("Flag sent to the host.", "info"); }
                    catch (e) { push(e.message, "error"); }
                  }}>⚑</button>
                )}
              </li>
            ))}
          </ol>
          <h3>Singing order</h3>
          <ol className="list compact">
            {turn && <li><strong>{turn.guest_name}</strong> <span className="pill">picking</span></li>}
            {state.upcoming.map((id, idx) => {
              const g = state.guests.find((x) => x.id === id);
              return g ? <li key={`${id}-${idx}`} className={id === myId ? "mine" : ""}>{g.name}{id === myId ? " (you)" : ""}</li> : null;
            })}
          </ol>
        </section>
      )}

      <footer className="phone-footer">
        <button className="btn btn-link" onClick={leave}>Leave event</button>
      </footer>
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
