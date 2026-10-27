import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, hostApi } from "../lib/api";
import { applyAppearance } from "../lib/schemes";
import { useCountdown, useEventSocket } from "../lib/useEventSocket";
import { decodeEntities, formatDuration } from "../lib/format";
import { singers } from "../lib/eta";
import { Toasts, useToasts } from "../components/Toasts";
import { SupersetChooser, SupersetLineup } from "../components/Superset";

/** The host's phone remote: playback, volume and queue control without walking to the TV. */
export default function HostRemote() {
  const { eventId } = useParams();
  const [code, setCode] = useState(null);
  const [error, setError] = useState("");
  const { toasts, push } = useToasts();
  const [choosing, setChoosing] = useState(false);

  useEffect(() => {
    api(`/api/host/events/${eventId}/state`).then((s) => setCode(s.event.join_code)).catch((e) => setError(e.message));
  }, [eventId]);

  const onMessage = useCallback((msg) => {
    if (msg.type === "notice" && !msg.for_guest_id) push(msg.data.text, msg.data.level);
  }, [push]);
  const { state, connected, serverNow } = useEventSocket(code, { onMessage });
  useEffect(() => { applyAppearance(state?.appearance); }, [state?.appearance]);
  const readyLeft = useCountdown(state?.now_playing?.starts_at || null, serverNow, 0);

  const act = async (action, confirmText) => {
    if (confirmText && !window.confirm(confirmText)) return;
    try { await hostApi.action(eventId, action); } catch (e) { push(e.message, "error"); }
  };
  const call = async (path, opts) => {
    try { await api(path, opts); } catch (e) { push(e.message, "error"); }
  };

  if (error) return <main className="phone center-page"><p className="error">{error}</p><Link to="/host">Back</Link></main>;
  if (!state) return <main className="phone center-page"><p className="muted">Connecting to the event…</p></main>;

  const ev = state.event;
  const np = state.now_playing;
  const gettingReady = !!np && readyLeft > 0;
  const sup = state.superset;
  const superset = !!sup;
  const vote = state.superset_vote;
  const waitingFor = sup?.waiting_for ? sup.slots.find((s) => s.guest_id === sup.waiting_for) : null;
  const paused = ev.paused;

  return (
    <div className={`phone remote ${superset ? "is-superset" : ""}`}>
      <header className="phone-top">
        <div>
          <div className="brand tiny">Kar<span>oulette</span> <span className="muted">remote</span></div>
          <div className="phone-event">{ev.name}</div>
        </div>
        <div className="phone-me">
          <span>Code {ev.join_code}</span>
          {!connected && <span className="error-tag small">Reconnecting…</span>}
        </div>
      </header>

      <section className={`status-card ${np ? "your-turn" : ""}`}>
        <div className="label">{np ? (gettingReady ? `Get ready · starts in ${Math.ceil(readyLeft)} s` : "Now singing") : "Nothing playing"}</div>
        {np ? (
          <>
            <div className="status-big">{singers(np)}</div>
            <div className="muted">{decodeEntities(np.title)}</div>
          </>
        ) : (
          <div className="muted">{ev.status === "active" ? "Queue a song or press Play next." : ev.status === "ended" ? "This event has ended." : "Start the event when everyone's ready."}</div>
        )}
        {state.round.number > 0 && (
          <div className="muted small">Round {state.round.number}{state.round.theme ? ` · ${state.round.theme.name}` : ""}{superset ? ` · ★ Superset: ${sup.theme}` : ""}</div>
        )}
        {vote && <div className="warning small">★ Superset vote by {vote.called_by_name}: yes {vote.yes} · no {vote.no} of {vote.eligible}</div>}
        {waitingFor && <div className="warning small">★ Waiting for {waitingFor.name} to pick their Superset song.</div>}
        {paused && <div className="warning small">🚬 Smoke break: the queue is on hold.</div>}
      </section>

      <section className="remote-pad">
        {ev.status !== "active" ? (
          <button className="btn btn-primary btn-xl wide" disabled={ev.status === "ended"} onClick={() => act("start")}>▶ Start event</button>
        ) : paused ? (
          <button className="btn btn-primary btn-xl wide" onClick={() => act("resume-queue")}>▶ Resume after the break</button>
        ) : gettingReady ? (
          <button className="btn btn-primary btn-xl wide" onClick={() => act("start-now")}>⏩ Start the song now</button>
        ) : np ? (
          <button className="btn btn-primary btn-xl wide" onClick={() => act("video-toggle")}>⏯ Pause / play</button>
        ) : (
          <button className="btn btn-primary btn-xl wide" disabled={!state.queue.length} onClick={() => act("play-next")}>▶ Play next song</button>
        )}
        <button className="btn btn-xl" onClick={() => act("volume-down")} aria-label="Volume down">🔉 −</button>
        <button className="btn btn-xl" onClick={() => act("volume-up")} aria-label="Volume up">🔊 +</button>
        <button className="btn btn-xl" disabled={!np && !state.queue.length} onClick={() => act("skip-song")}>⏭ Skip</button>
        <button className="btn btn-xl" disabled={!np} onClick={() => act("stop-playback")} title="Stop and put the song back at the front">⏹ Stop</button>
        {ev.status === "active" && !paused && (
          <button className="btn btn-xl wide" onClick={() => act("pause-queue")}>🚬 Smoke break (pause queue)</button>
        )}
        {waitingFor && (
          <button className="btn wide" onClick={() => act("superset-skip-turn")}>⏭ Skip {waitingFor.name}'s Superset turn</button>
        )}
        {ev.config.themes_enabled && <button className="btn" disabled={!state.round.number} onClick={() => act("spin")}>🎰 Re-spin theme</button>}
        {(superset || vote)
          ? <button className="btn" onClick={() => act("superset-cancel", superset ? "End the Superset? Picks not sung yet are dropped." : null)}>✖ Cancel superset</button>
          : <button className="btn btn-gold" disabled={ev.status !== "active"} onClick={() => setChoosing(true)}>★ Superset</button>}
      </section>

      {sup && (
        <section className="card">
          <h3>★ Superset: {sup.theme}</h3>
          <SupersetLineup superset={sup} />
        </section>
      )}

      <section className="card">
        <h3>{sup ? "Then the queue" : "Queue"} ({state.queue.length})</h3>
        {!state.queue.length && <p className="muted">Nothing queued yet.</p>}
        <ol className="results">
          {state.queue.map((item, idx) => (
            <li key={item.id} className="result">
              <div className="r-text">
                <div className="r-title">{decodeEntities(item.title)}</div>
                <div className="r-meta">{idx === 0 ? "Up next · " : ""}{singers(item)}
                  {item.duration_s ? ` · ${formatDuration(item.duration_s)}` : ""}</div>
              </div>
              <div className="song-actions row">
                <button className="btn" title="Play next" disabled={idx === 0}
                        onClick={() => call(`/api/host/events/${eventId}/queue/${item.id}/play-next`, { method: "POST" })}>⤒</button>
                <button className="btn btn-danger" title="Remove"
                        onClick={() => window.confirm(`Remove “${decodeEntities(item.title)}”?`) &&
                          call(`/api/host/events/${eventId}/queue/${item.id}`, { method: "DELETE" })}>✕</button>
              </div>
            </li>
          ))}
        </ol>
      </section>

      <footer className="phone-footer row wrap remote-footer">
        <Link className="btn" to="/host/admin">Admin</Link>
        <Link className="btn" to={`/host/event/${eventId}`}>TV screen</Link>
        <Link className="btn" to="/help?for=host">❓ Help</Link>
        <button className="btn btn-danger" disabled={ev.status === "ended"}
                onClick={() => act("end", "End this event for everyone? The queue will be cleared.")}>End event</button>
      </footer>
      {choosing && (
        <SupersetChooser nowPlaying={np} title="Declare a Superset" onClose={() => setChoosing(false)}
                         onChoose={(mode) => { setChoosing(false); act(`superset-${mode}`); }} />
      )}
      <Toasts toasts={toasts} />
    </div>
  );
}
