import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, hostApi } from "../lib/api";
import { applyScheme } from "../lib/schemes";
import { useCountdown, useEventSocket } from "../lib/useEventSocket";
import { decodeEntities, formatDuration } from "../lib/format";
import YouTubePlayer from "../components/YouTubePlayer";
import ThemeSpinner from "../components/ThemeSpinner";
import Recap from "../components/Recap";
import { SupersetChooser, SupersetLineup } from "../components/Superset";
import { Toasts, useToasts } from "../components/Toasts";
import { singers } from "../lib/eta";

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
  const [reactions, setReactions] = useState([]);
  const [bouched, setBouched] = useState(null);
  const [cheers, setCheers] = useState({ itemId: null, count: 0 });
  const [showRemote, setShowRemote] = useState(false);
  const [choosing, setChoosing] = useState(false);
  const { toasts, push } = useToasts();
  const playerRef = useRef(null);
  const hideTimer = useRef(null);
  const pausedRef = useRef(false);

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
        // Bouches, smoke breaks and Supersets get the whole screen, so skip their toasts here.
        if (!msg.for_guest_id && !["bouched", "paused", "superset", "last_call"].includes(d.kind)) push(d.text, d.level);
        break;
      case "bouched":
        setBouched(d.name);
        setTimeout(() => setBouched(null), 6000);
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
          setSupersetFlash({ theme: d.spun ? null : d.theme?.name || "your pick" });
          setTimeout(() => setSupersetFlash(null), 4000);
        }
        break;
      case "song_flagged":
        push(`⚑ “${decodeEntities(d.title)}” was flagged as off-theme (${d.count})`, "warning");
        break;
      case "reaction": {
        // Float the emoji up the screen from a random spot near the bottom; keep at most 40 on screen.
        const id = Math.random().toString(36).slice(2);
        const r = { id, emoji: d.emoji, name: d.name, left: 8 + Math.random() * 84, drift: Math.random() * 60 - 30 };
        setReactions((list) => [...list.slice(-39), r]);
        setTimeout(() => setReactions((list) => list.filter((x) => x.id !== id)), 3600);
        if (d.item_id) setCheers((c) => ({ itemId: d.item_id, count: Math.max(d.cheers, c.itemId === d.item_id ? c.count : 0) }));
        break;
      }
      case "video_command":
        if (d.command === "toggle") playerRef.current?.toggle();
        else {
          const level = playerRef.current?.volume(d.command === "volume_up" ? 10 : -10);
          if (level !== null && level !== undefined) push(`${level ? "🔊" : "🔇"} Volume ${level}`, "info", 2000);
        }
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
      else if (e.key === "g" || e.key === "G") act("start-now");
      else if (e.key === "p" || e.key === "P") act(pausedRef.current ? "resume-queue" : "pause-queue");
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [act]);

  const nowPlaying = state?.now_playing;
  const round = state?.round;
  const spinLeft = useCountdown(round?.spun_at ? round.spun_at + round.spin_seconds : null, serverNow, 0);
  const spinning = !!round?.spun_at && spinLeft > 0;
  const readyLeft = useCountdown(nowPlaying?.starts_at || null, serverNow, 0);
  const gettingReady = !!nowPlaying && readyLeft > 0;
  const vote = state?.superset_vote;
  const sup = state?.superset;
  const setSpinLeft = useCountdown(sup?.spun_at ? sup.spun_at + sup.spin_seconds : null, serverNow, 0);
  const setSpinning = !!sup?.spun_at && setSpinLeft > 0;
  const voteLeft = useCountdown(vote?.ends_at || null, serverNow, 0);
  pausedRef.current = !!state?.event.paused;

  if (!checked) {
    return <PremiumChecklist onContinue={() => {
      try { sessionStorage.setItem(CHECK_KEY, "1"); } catch { /* ignore */ }
      setChecked(true);
    }} />;
  }
  if (error) return <main className="center-page"><p className="error">{error}</p><Link to="/host">Back</Link></main>;
  if (!state) return <main className="center-page"><p className="muted">Connecting to the event…</p></main>;

  const ev = state.event;
  const superset = !!sup;
  const themesOn = !!ev.config.themes_enabled;
  const waitingFor = sup?.waiting_for ? sup.slots.find((s) => s.guest_id === sup.waiting_for) : null;
  const paused = ev.paused;
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
  const setTheme = setSpinning ? (
    <ThemeSpinner spinKey={`set-${sup.id}-${sup.spun_at}`} candidates={spinMeta.candidates || themes}
                  result={sup.theme} duration={sup.spin_seconds} superset size={idle ? "xl" : "lg"} />
  ) : sup && <div className="theme-pill superset">{sup.theme}</div>;
  const supersetPanel = sup && (
    <div className="side-card turn-panel superset-panel">
      <div className="label">★ Superset · everyone sings</div>
      {setTheme}
      {sup.inspired_by && !setSpinning && <div className="turn-sub small">Kicked off by “{decodeEntities(sup.inspired_by)}”</div>}
      {sup.description && !setSpinning && <div className="turn-sub small">{sup.description}</div>}
      <SupersetLineup superset={sup} />
      <div className="turn-sub small">Pick a song that fits on your phone. Then the queue carries on.</div>
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
          {superset && <span className="superset-tag">SUPERSET · {setSpinning ? "spinning…" : sup.theme}</span>}
          {state.last_call && (
            <span className={`last-call-tag ${state.last_call.open ? "" : "closed"}`}>
              🔔 {state.last_call.open
                ? `Closing ${state.last_call.closing_text} · room for about ${state.last_call.room} more song${state.last_call.room === 1 ? "" : "s"}`
                : `Last call! The queue runs to ${state.last_call.closing_text}`}
            </span>
          )}
          {!connected && <span className="error-tag">Reconnecting…</span>}
        </div>
      </header>

      {newSinger && (
        <div className="superset-flash newsinger-flash" aria-live="assertive">
          <div className="superset-word">NEW SINGER!</div>
          <div className="superset-theme">Please welcome {newSinger} 🎤</div>
        </div>
      )}

      {bouched && (
        <div className="superset-flash bouche-flash" aria-live="assertive">
          <div className="superset-word">BOUCHED!</div>
          <div className="superset-theme">🥖 {bouched} has been BOUCHED! 🥖</div>
        </div>
      )}

      {supersetFlash && (
        <div className="superset-flash" aria-live="assertive">
          <div className="superset-word">SUPERSET!</div>
          <div className="superset-theme">{supersetFlash.theme ? `Everyone sings: ${supersetFlash.theme}` : "Spinning the theme…"}</div>
        </div>
      )}

      <main className="tv-main">
        <section className="tv-stage">
          <div className="player-wrap">
            <YouTubePlayer ref={playerRef} videoId={gettingReady ? null : nowPlaying?.video_id} itemId={nowPlaying?.id}
                           onStateChange={setPlayerState}
                           onEnded={(itemId) => call(`/api/host/events/${eventId}/player`,
                             { method: "POST", body: { item_id: itemId, state: "ended" } })}
                           onError={(itemId, code) => call(`/api/host/events/${eventId}/player`,
                             { method: "POST", body: { item_id: itemId, state: "error", code } })} />
            {gettingReady && (
              <div className="idle-overlay get-ready" aria-live="assertive">
                <div className="get-ready-box">
                  <div className="label">Get ready!</div>
                  <div className="get-ready-name">{singers(nowPlaying)}</div>
                  <div className="get-ready-title">{decodeEntities(nowPlaying.title)}</div>
                  <div className="get-ready-count" key={Math.ceil(readyLeft)}>{Math.ceil(readyLeft)}</div>
                  <div className="muted">Grab the mic! The song starts when the countdown ends.</div>
                </div>
              </div>
            )}
            {idle && ev.status === "ended" && state.recap && (
              <div className="idle-overlay recap-overlay"><Recap recap={state.recap} eventName={ev.name} /></div>
            )}
            {idle && paused && (
              <div className="idle-overlay smoke-break" aria-live="assertive">
                <div className="smoke" aria-hidden="true"><span /><span /><span /></div>
                <div className="smoke-text">
                  <div className="smoke-word">Smoke break!</div>
                  <div className="smoke-sub">The music's on hold. Keep adding songs: we'll be right back.</div>
                  <div className="join-code">Join at {joinUrl.replace(/^https?:\/\//, "")} · Code <strong>{ev.join_code}</strong></div>
                </div>
              </div>
            )}
            {idle && !paused && waitingFor && (
              <div className="idle-overlay set-waiting" aria-live="polite">
                <div className="smoke-text">
                  <div className="label">★ Superset</div>
                  {setTheme}
                  <div className="smoke-sub">Waiting for <strong>{waitingFor.name}</strong> to pick a song that fits…</div>
                  <div className="muted">Pick on your phone, or tap “Sit this one out”.</div>
                  <button className={`btn ${controlsVisible ? "" : "hidden"}`} onClick={() => act("superset-skip-turn")}>
                    ⏭ Skip {waitingFor.name}'s turn</button>
                </div>
              </div>
            )}
            {idle && !paused && !waitingFor && !(ev.status === "ended" && state.recap) && (
              <div className="idle-overlay">
                {spinning ? roundPanel : setSpinning ? supersetPanel : (
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
            <div className="reactions-layer" aria-hidden="true">
              {reactions.map((r) => (
                <span key={r.id} className="reaction" style={{ left: `${r.left}%`, "--drift": `${r.drift}px` }}>
                  {r.emoji}<small>{r.name}</small>
                </span>
              ))}
            </div>
          </div>
          {nowPlaying && (
            <div className="now-singing">
              <div className="label">{gettingReady ? "Up now" : "Now singing"}</div>
              <div className="now-name">{singers(nowPlaying)}</div>
              <div className="now-title">{decodeEntities(nowPlaying.title)}</div>
              {nowPlaying.is_superset && nowPlaying.flags > 0 && <span className="flag-badge">⚑ {nowPlaying.flags}</span>}
              {(() => {
                const count = cheers.itemId === nowPlaying.id ? Math.max(cheers.count, nowPlaying.cheers) : nowPlaying.cheers;
                const full = Math.max(10, state.guests.length * 3); // the meter fills at ~3 cheers a guest
                return count > 0 && (
                  <span className="crowd-meter" title="Crowd meter: cheers from phones">
                    <span className="crowd-bar"><span style={{ width: `${Math.min(100, (count / full) * 100)}%` }} /></span>
                    🔥 {count}
                  </span>
                );
              })()}
            </div>
          )}
        </section>

        <aside className="tv-side">
          {vote && (
            <div className="side-card vote-panel" aria-live="polite">
              <div className="label">★ Superset vote · {Math.ceil(voteLeft)} s</div>
              <div className="vote-title"><strong>{vote.called_by_name}</strong> calls a Superset
                {vote.mode === "now" && vote.song ? <>, kicked off by <strong>“{decodeEntities(vote.song)}”</strong></> : " after this song"}</div>
              <div className="vote-bars">
                <div className="vote-bar yes"><span style={{ width: `${(vote.yes / Math.max(1, vote.eligible)) * 100}%` }} /><b>Yes {vote.yes}</b></div>
                <div className="vote-bar no"><span style={{ width: `${(vote.no / Math.max(1, vote.eligible)) * 100}%` }} /><b>No {vote.no}</b></div>
              </div>
              <div className="turn-sub small">Vote on your phone! Majority wins ({vote.yes + vote.no} of {vote.eligible} voted).</div>
            </div>
          )}
          {sup ? !(idle && setSpinning) && supersetPanel : themesOn && !(idle && spinning) && roundPanel}

          <div className="side-card grow">
            <div className="label">{sup ? "Then the queue" : "Up next · Queue"} ({state.queue.length})</div>
            {!upNext && <div className="muted">Nothing queued yet</div>}
            <ol className="queue">
              {state.queue.map((item, idx) => (
                <li key={item.id} className={`queue-item ${idx === 0 && !sup ? "next" : ""}`}>
                  <img src={item.thumbnail} alt="" loading="lazy" />
                  <div className="q-text">
                    <div className="q-title">{decodeEntities(item.title)}</div>
                    <div className="q-meta">
                      {idx === 0 && !sup && <span className="next-tag">Up next</span>}
                      <span className="q-singer">{singers(item)}</span>
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
        {ev.status === "active" && (paused
          ? <button className="btn btn-primary" onClick={() => act("resume-queue")}>▶ Resume queue</button>
          : <button className="btn" onClick={() => act("pause-queue")}>🚬 Pause queue</button>)}
        {paused ? null : gettingReady ? (
          <button className="btn btn-primary" onClick={() => act("start-now")}>⏩ Start now</button>
        ) : (
          <button className="btn" onClick={() => (nowPlaying ? playerRef.current?.toggle() : act("play-next"))}>
            {playerState === 1 ? "⏸ Pause video" : "▶ Play video"}
          </button>
        )}
        <button className="btn" onClick={() => act("skip-song")} disabled={!nowPlaying && !state.queue.length}>⏭ Skip song</button>
        {themesOn && <button className="btn" onClick={() => act("spin")} disabled={!round.number}>🎰 Re-spin theme</button>}
        {(superset || vote)
          ? <button className="btn" onClick={() => act("superset-cancel", superset ? "End the Superset? Picks not sung yet are dropped." : null)}>✖ Cancel superset</button>
          : <button className="btn btn-gold" disabled={ev.status !== "active"} onClick={() => setChoosing(true)}>★ Superset</button>}
        <span className="spacer" />
        <button className="btn" onClick={() => setShowRemote(true)}>📱 Remote</button>
        <Link className="btn" to="/host/admin">Admin</Link>
        <button className="btn" onClick={() => document.documentElement.requestFullscreen?.()}>⛶</button>
        <button className="btn btn-danger" disabled={ev.status === "ended"}
                onClick={() => act("end", "End this event for everyone? The queue will be cleared.")}>End event</button>
      </footer>
      {choosing && (
        <SupersetChooser nowPlaying={nowPlaying} title="Declare a Superset" onClose={() => setChoosing(false)}
                         onChoose={(mode) => { setChoosing(false); act(`superset-${mode}`); }} />
      )}
      {showRemote && (
        <div className="modal-backdrop" onClick={() => setShowRemote(false)}>
          <div className="card modal" onClick={(e) => e.stopPropagation()}>
            <h2>Phone remote</h2>
            <p className="muted">Scan with your phone to skip, pause, change the volume and manage the queue from
              anywhere in the room. You'll sign in with the host PIN.</p>
            <img className="remote-qr" src={`/api/host/events/${eventId}/remote-qr.svg`} alt="QR code for the host remote" />
            <p className="join-url small">{joinUrl.replace(/\/join\/[^/]+$/, "")}/host/remote/{eventId}</p>
            <button className="btn btn-primary btn-block" onClick={() => setShowRemote(false)}>Done</button>
          </div>
        </div>
      )}
      <Toasts toasts={toasts} />
    </div>
  );
}
