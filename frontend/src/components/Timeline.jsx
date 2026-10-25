import { useEffect, useMemo, useState } from "react";
import { api } from "../lib/api";

const KINDS = [
  ["", "Everything"], ["playback", "Playback"], ["songs", "Songs"], ["singers", "Singers"],
  ["superset", "Supersets"], ["event", "Event"], ["settings", "Settings"],
];
const ICON = { playback: "▶", songs: "🎵", singers: "🙋", superset: "★", event: "📅", settings: "⚙" };
const time = (t) => new Date(t * 1000).toLocaleTimeString("en-CA", { hour: "numeric", minute: "2-digit", second: "2-digit" });

/** Host admin: everything that happened at an event, who did it and when (filterable, CSV export). */
export default function Timeline({ eventId, push }) {
  const [rows, setRows] = useState(null);
  const [kind, setKind] = useState("");
  const [who, setWho] = useState("");
  const [q, setQ] = useState("");
  const load = () => api(`/api/host/events/${eventId}/timeline`).then(setRows).catch((e) => push(e.message, "error"));
  useEffect(() => { load(); }, [eventId]);

  const people = useMemo(() => [...new Set((rows || []).map((r) => r.actor_name))].sort(), [rows]);
  const shown = useMemo(() => {
    const needle = q.trim().toLocaleLowerCase("en-CA");
    return (rows || []).filter((r) => (!kind || r.kind === kind) && (!who || r.actor_name === who)
      && (!needle || r.text.toLocaleLowerCase("en-CA").includes(needle))).slice().reverse();
  }, [rows, kind, who, q]);

  return (
    <section className="card">
      <div className="history-list-head">
        <h2>Timeline</h2>
        <div className="row wrap">
          <button type="button" className="btn" onClick={load}>Refresh</button>
          <a className="btn" href={`/api/host/events/${eventId}/timeline.csv`}>⬇ CSV</a>
        </div>
      </div>
      <p className="muted small">Everything that happened at this event, newest first: who added, skipped, moved or removed
        what, and which round each song landed in. Handy when something on the night looked odd.</p>
      <div className="history-filters">
        <select value={kind} onChange={(e) => setKind(e.target.value)} aria-label="What">
          {KINDS.map(([k, label]) => <option key={k} value={k}>{label}</option>)}
        </select>
        <select value={who} onChange={(e) => setWho(e.target.value)} aria-label="Who">
          <option value="">Anyone</option>
          {people.map((p) => <option key={p} value={p}>{p}</option>)}
        </select>
        <input type="search" placeholder="Search the timeline" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search the timeline" />
      </div>
      {rows === null ? <p className="muted">Loading…</p> : !shown.length ? <p className="muted">Nothing to show.</p> : (
        <ol className="timeline">
          {shown.map((r) => (
            <li key={r.id} className={`tl-${r.kind}`}>
              <span className="tl-time">{time(r.at)}</span>
              <span className="tl-icon" aria-hidden="true">{ICON[r.kind] || "•"}</span>
              <span className="tl-text">{r.text}
                <small className={`tl-who tl-${r.actor_type}`}>{r.actor_type === "system" ? "automatic" : r.actor_name}</small>
              </span>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}
