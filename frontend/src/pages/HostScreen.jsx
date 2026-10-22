import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, hostApi } from "../lib/api";
import { applyScheme } from "../lib/schemes";
import { useCountdown, useEventSocket } from "../lib/useEventSocket";
import { decodeEntities, formatDuration } from "../lib/format";
import YouTubePlayer from "../components/YouTubePlayer";
import ThemeSpinner from "../components/ThemeSpinner";
import { Toasts, useToasts } from "../components/Toasts";

const CHECK_KEY = "kq_premium_checked";

function PremiumChecklist({ onContinue }) {
  const items = [
    ["premium", "This browser is signed in to the YouTube Premium account (open youtube.com and check your avatar shows Premium)."],
    ["audio", "TV and sound system are connected, and the volume is up."],
    ["autoplay", "Autoplay with sound is allowed for this site in the browser settings."],
    ["fullscreen", "The browser window is on the TV and ready for full screen (F11 or the button below)."],
  ];
  const [checked, setChecked] = useState({});
  const ready = items.every(([k]) => checked[k]);
  return (
    <main className="center-page">
      <div className="card checklist">
        <h1 className="brand small">Kar<span>oulette</span></h1>
        <h2>Before we start</h2>
        <p className="muted">Ad-free playback relies on this browser being signed in to YouTube Premium.
          Karoulette never downloads or rips video; it plays YouTube's own player.</p>
        <ul className="checks">
          {items.map(([key, text]) => (
            <li key={key}>
              <label>
                <input type="checkbox" checked={!!checked[key]}
                       onChange={(e) => setChecked((c) => ({ ...c, [key]: e.target.checked }))} />
                <span>{text}</span>
              </label>
            </li>
          ))}
        </ul>
        <div className="row">
          <a className="btn" href="https://www.youtube.com/paid_memberships" target="_blank" rel="noreferrer">
            Check Premium status
          </a>
          <button className="btn" type="button" onClick={() => document.documentElement.requestFullscreen?.()}>
            Go full screen
          </button>
          <button className="btn btn-primary" disabled={!ready} onClick={onContinue}>Continue</button>
        </div>
      </div>
    </main>
  );
}

export default function HostScreen() {
  const { eventId } = useParams();
  const [checked, setChecked] = useState(() => {
    try { return sessionStorage.getItem(CHECK_KEY) === "1"; } catch { return false; }
  });
  const [code, setCode] = useState(null);
  const [joinUrl, setJoinUrl] = useState("");
  const [themes, setThemes] = useState([]);
  const [error, setError] = useState("");
  const [controlsVisible, setControlsVisible] = useState(true);
  const [supersetFlash, setSupersetFlash] = useState(null);
  const [newSinger, setNewSinger] = useState(null);
  const [spinMeta, setSpinMeta] = useState({ duration: 5 });
  const [playerState, setPlayerState] = useState(-1);
  const { toasts, push } = useToasts();
  const playerRef = useRef(null);
  const hideTimer = useRef(null);

  useEffect(() => {
    api(`/api/host/events/${eventId}/state`)
      .then((s) => {
        setCode(s.event.join_code);
        return api(`/api/public/join-url?code=${s.event.join_code}`);
      })
      .then((r) => setJoinUrl(r.url))
      .catch((e) => setError(e.message));
    api("/api/public/themes").then(setThemes).catch(() => {});
  }, [eventId]);

  const onMessage = useCallback((msg) => {
    const d = msg.data || {};
    switch (msg.type) {
      case "notice":
        if (!msg.for_guest_id) push(d.text, d.level);
        break;
      case "guest_joined":
        if (!d.new_singer) push(`🎉 ${d.name} joined the party!`, "success");  // new singers get a notice
        break;
      case "new_singer":
        setNewSinger(d.name);
        setTimeout(() => setNewSinger(null), 7000);
        break;
      case "theme_spun":
        setSpinMeta({ duration: d.duration, candidates: d.candidates });
        if (d.candidates?.length) setThemes(d.candidates);
        break;
      case "superset":
        if (d.active) {
          setSupersetFlash(d.theme?.name || "Superset");
          setTimeout(() => setSupersetFlash(null), 4000);
        }
        break;
      case "song_flagged":
        push(`⚑ “${decodeEntities(d.title)}” was flagged as off-theme (${d.count})`, "warning");
        break;
      default:
        break;
    }
  }, [push]);

  const { state, connected, serverNow } = useEventSocket(checked ? code : null, { onMessage });
  useEffect(() => { if (state?.appearance) applyScheme(state.appearance.scheme); }, [state?.appearance?.scheme]);

  const act = useCallback(async (action, confirmText) => {
    if (confirmText && !window.confirm(confirmText)) return;
    try {
      await hostApi.action(eventId, action);
    } catch (e) {
      push(e.message, "error");
    }
  }, [eventId, push]);

  const call = useCallback(async (path, opts) => {
    try { await api(path, opts); } catch (e) { push(e.message, "error"); }
  }, [push]);

  // Show controls on mouse movement; hide after a few seconds of inactivity.
  useEffect(() => {
    const show = () => {
      setControlsVisible(true);
      clearTimeout(hideTimer.current);
      hideTimer.current = setTimeout(() => setControlsVisible(false), 6000);
    };
    window.addEventListener("mousemove", show);
    show();
    return () => { window.removeEventListener("mousemove", show); clearTimeout(hideTimer.current); };
  }, []);

  useEffect(() => {
    const onKey = (e) => {
      if (e.target.tagName === "INPUT" || e.target.tagName === "TEXTAREA") return;
      if (e.key === " ") { e.preventDefault(); playerRef.current?.toggle(); }
      else if (e.key === "n" || e.key === "N") act("skip-song");
      else if (e.key === "s" || e.key === "S") act("spin");
      else if (e.key === "h" || e.key === "H") setControlsVisible((v) => !v);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [act]);

  const nowPlaying = state?.now_playing;
  const round = state?.round;
  const spinLeft = useCountdown(round?.spun_at ? round.spun_at + round.spin_seconds : null, serverNow, 0);
  const spinning = !!round?.spun_at && spinLeft > 0;

  if (!checked) {
    return <PremiumChecklist onContinue={() => {
      try { sessionStorage.setItem(CHECK_KEY, "1"); } catch { /* ignore */ }
      setChecked(true);
    }} />;
  }
  if (error) return <main className="center-page"><p className="error">{error}</p><Link to="/host">Back</Link></main>;
  if (!state) return <main className="center-page"><p className="muted">Connecting to the event…</p></main>;

  const ev = state.event;
  const superset = state.round.is_superset;
  const qrSrc = `/api/public/qr.svg?code=${ev.join_code}`;
  const upNext = state.queue[0];
  const idle = !nowPlaying;

  const roundPanel = (
    <div className={`turn-panel round-panel ${spinning ? "spinning" : ""}`}>
      <div className="label">{round.number ? `Round ${round.number} theme` : "Theme"}</div>
      {spinning ? (
        <ThemeSpinner spinKey={`${round.number}-${round.spun_at}`} candidates={spinMeta.candidates || themes}
                      result={round.theme?.name} duration={round.spin_seconds} superset={superset}
                      size={idle ? "xl" : "lg"} />
      ) : round.theme ? (
        <>
          <div className={`theme-pill ${superset ? "superset" : ""}`}>{round.theme.name}</div>
          {round.theme.description && <div className="turn-sub">{round.theme.description}</div>}
        </>
      ) : (
        <div className="turn-sub">{ev.status !== "active" ? "Press Start when everyone's ready." : "No theme this round."}</div>
      )}
      {round.theme && !spinning && (
        <div className="turn-sub small">{superset ? "Superset: every song this round must fit!" : "A suggestion for your next pick."}</div>
      )}
    </div>
  );
  const order = state.guests.map((g) => g.name);
  const newNames = new Set(state.guests.filter((g) => g.new_singer).map((g) => g.id));

  return (
    <div className={`tv ${superset ? "is-superset" : ""}`}>
      <header className="tv-top">
        <div className="tv-title">
          <span className="brand tiny">Kar<span>oulette</span></span>
          <span className="tv-event">{ev.name}</span>
        </div>
        <div className="tv-round">
          {state.round.number > 0 && <span>Round {state.round.number}</span>}
          {superset && <span className="superset-tag">SUPERSET · {state.round.theme?.name}</span>}
          {ev.superset_pending === "force" && !superset && <span className="pending-tag">Superset next round!</span>}
          {!connected && <span className="error-tag">Reconnecting…</span>}
        </div>
      </header>

      {newSinger && (
        <div className="superset-flash newsinger-flash" aria-live="assertive">
          <div className="superset-word">NEW SINGER!</div>
          <div className="superset-theme">Please welcome {newSinger} 🎤</div>
        </div>
      )}

      {supersetFlash && (
        <div className="superset-flash" aria-live="assertive">
          <div className="superset-word">SUPERSET!</div>
          <div className="superset-theme">Everyone sings: {supersetFlash}</div>
        </div>
      )}

      <main className="tv-main">
        <section className="tv-stage">
          <div className="player-wrap">
            <YouTubePlayer ref={playerRef} videoId={nowPlaying?.video_id} itemId={nowPlaying?.id}
                           onStateChange={setPlayerState}
                           onEnded={(itemId) => call(`/api/host/events/${eventId}/player`,
                             { method: "POST", body: { item_id: itemId, state: "ended" } })}
                           onError={(itemId, code) => call(`/api/host/events/${eventId}/player`,
                             { method: "POST", body: { item_id: itemId, state: "error", code } })} />
            {idle && (
              <div className="idle-overlay">
                {spinning ? roundPanel : (
                  <>
                    <img className="qr-big" src={qrSrc} alt={`QR code to join ${ev.name}`} />
                    <div className="idle-text">
                      <div className="big">Scan to join</div>
                      <div className="join-url">{joinUrl}</div>
                      <div className="join-code">Code <strong>{ev.join_code}</strong></div>
                      <div className="muted">{state.queue.length ? "Up next in a moment…" : "The queue is empty. Pick a song on your phone!"}</div>
                    </div>
                  </>
                )}
              </div>
            )}
          </div>
          {nowPlaying && (
            <div className="now-singing">
              <div className="label">Now singing</div>
              <div className="now-name">{nowPlaying.guest_name}</div>
              <div className="now-title">{decodeEntities(nowPlaying.title)}</div>
              {nowPlaying.is_superset && nowPlaying.flags > 0 && <span className="flag-badge">⚑ {nowPlaying.flags}</span>}
            </div>
          )}
        </section>

        <aside className="tv-side">
          {!(idle && spinning) && roundPanel}

          <div className="side-card grow">
            <div className="label">Up next · Queue ({state.queue.length})</div>
            {!upNext && <div className="muted">Nothing queued yet</div>}
            <ol className="queue">
              {state.queue.map((item, idx) => (
                <li key={item.id} className={`queue-item ${idx === 0 ? "next" : ""}`}>
                  <img src={item.thumbnail} alt="" loading="lazy" />
                  <div className="q-text">
                    <div className="q-title">{decodeEntities(item.title)}</div>
                    <div className="q-meta">
                      {idx === 0 && <span className="next-tag">Up next</span>}
                      <span className="q-singer">{item.guest_name}</span>
                      {newNames.has(item.guest_id) && <span className="new-tag">New</span>}
                      {item.duration_s ? ` · ${formatDuration(item.duration_s)}` : ""}
                      {item.round && !item.priority ? ` · R${item.round}` : ""}
                      {item.is_superset && item.flags > 0 && <span className="flag-badge">⚑ {item.flags}</span>}
                    </div>
                  </div>
                  <div className={`q-actions ${controlsVisible ? "" : "hidden"}`}>
                    <button title="Play next" disabled={idx === 0}
                            onClick={() => call(`/api/host/events/${eventId}/queue/${item.id}/play-next`,
                              { method: "POST" })}>⤒</button>
                    <button title="Remove" className="danger"
                            onClick={() => window.confirm(`Remove “${decodeEntities(item.title)}”?`) &&
                              call(`/api/host/events/${eventId}/queue/${item.id}`, { method: "DELETE" })}>✕</button>
                  </div>
                </li>
              ))}
            </ol>
          </div>

          <div className="side-card join-card">
            <img src={qrSrc} alt="Join QR code" />
            <div>
              <div className="label">Join the queue</div>
              <div className="join-url small">{joinUrl}</div>
              <div className="join-code">Code <strong>{ev.join_code}</strong></div>
              <div className="muted small">
                Singers: {order.length}{order.length > 0 && ` · ${order.slice(0, 4).join(", ")}${order.length > 4 ? "…" : ""}`}
              </div>
            </div>
          </div>
        </aside>
      </main>

      <footer className={`controls ${controlsVisible ? "" : "hidden"}`}>
        {ev.status !== "active" && (
          <button className="btn btn-primary" onClick={() => act("start")} disabled={ev.status === "ended"}>▶ Start event</button>
        )}
        <button className="btn" onClick={() => (nowPlaying ? playerRef.current?.toggle() : act("play-next"))}>
          {playerState === 1 ? "⏸ Pause video" : "▶ Play video"}
        </button>
        <button className="btn" onClick={() => act("skip-song")} disabled={!nowPlaying && !state.queue.length}>⏭ Skip song</button>
        <button className="btn" onClick={() => act("spin")} disabled={!round.number}>🎰 Re-spin theme</button>
        {(superset || ev.superset_pending === "force")
          ? <button className="btn" onClick={() => act("superset-cancel")}>✖ Cancel superset</button>
          : <button className="btn btn-gold" onClick={() => act("superset-force")}>★ Force superset</button>}
        <span className="spacer" />
        <Link className="btn" to="/host/admin">Admin</Link>
        <button className="btn" onClick={() => document.documentElement.requestFullscreen?.()}>⛶</button>
        <button className="btn btn-danger" disabled={ev.status === "ended"}
                onClick={() => act("end", "End this event for everyone? The queue will be cleared.")}>End event</button>
      </footer>
      <Toasts toasts={toasts} />
    </div>
  );
}
