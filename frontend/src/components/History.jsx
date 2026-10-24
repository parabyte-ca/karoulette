import { useMemo, useState } from "react";
import { decodeEntities } from "../lib/format";

const day = (t) => new Date(t * 1000).toLocaleDateString("en-CA", { year: "numeric", month: "short", day: "numeric" });
const time = (t) => new Date(t * 1000).toLocaleTimeString("en-CA", { hour: "numeric", minute: "2-digit" });
const isoDay = (t) => {
  const d = new Date(t * 1000);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
};
const songKey = (s) => decodeEntities(s.song).toLocaleLowerCase("en-CA").replace(/\s+/g, " ").trim();
const PAGE = 100;

/** Count rows by key, most first: [[label, count, key], ...]. */
function rank(rows, keyOf, labelOf, limit = 10) {
  const counts = new Map();
  for (const r of rows) {
    for (const k of [].concat(keyOf(r)).filter(Boolean)) {
      const c = counts.get(k) || { label: labelOf(r, k), n: 0 };
      c.n += 1;
      counts.set(k, c);
    }
  }
  return [...counts.entries()].map(([k, c]) => [c.label, c.n, k])
    .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0])).slice(0, limit);
}

/** A ranked list as thin horizontal bars, one colour. Each row is a button that filters the list. */
function BarList({ title, rows, onPick, empty, unit = "song" }) {
  const max = Math.max(1, ...rows.map((r) => r[1]));
  return (
    <section className="chart-card">
      <h3>{title}</h3>
      {rows.length === 0 ? <p className="muted small">{empty}</p> : (
        <ol className="bar-list">
          {rows.map(([label, n, key]) => {
            const tip = `${label}: ${n} ${unit}${n === 1 ? "" : "s"}`;
            return (
              <li key={key}>
                <button type="button" className="bar-row" onClick={() => onPick?.(key)} title={tip} aria-label={tip}>
                  <span className="bar-label">{label}</span>
                  <span className="bar-track"><span className="bar" style={{ width: `${(n / max) * 100}%` }} /></span>
                  <span className="bar-value">{n}</span>
                </button>
              </li>
            );
          })}
        </ol>
      )}
    </section>
  );
}

function toCsv(rows) {
  const cell = (v) => {
    const s = v === null || v === undefined ? "" : String(v);
    return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  const head = ["date", "time", "event", "singer", "duet_with", "song", "channel", "status", "superset", "theme",
    "round", "cheers", "youtube_url"];
  const lines = rows.map((r) => [isoDay(r.at), time(r.at), r.event, r.singer_group, r.duet_group || "",
    decodeEntities(r.title), r.channel, r.status, r.superset ? "yes" : "no", r.theme || "", r.round || "", r.cheers,
    `https://www.youtube.com/watch?v=${r.video_id}`].map(cell).join(","));
  return "﻿" + [head.join(","), ...lines].join("\n");
}

function download(rows) {
  const url = URL.createObjectURL(new Blob([toCsv(rows)], { type: "text/csv;charset=utf-8" }));
  const a = Object.assign(document.createElement("a"), { href: url, download: `karoulette-song-history-${isoDay(Date.now() / 1000)}.csv` });
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

/** Every song sung at every event: filters, stats, the list and a CSV of what's showing. */
export default function HistoryDashboard({ songs }) {
  const [q, setQ] = useState("");
  const [eventId, setEventId] = useState("");
  const [singer, setSinger] = useState("");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [status, setStatus] = useState("");
  const [shown, setShown] = useState(PAGE);

  const events = useMemo(() => {
    const seen = new Map();
    for (const s of songs) if (!seen.has(s.event_id)) seen.set(s.event_id, { id: s.event_id, name: s.event, date: s.event_date });
    return [...seen.values()].sort((a, b) => b.date - a.date);
  }, [songs]);
  const singers = useMemo(() => [...new Set(songs.flatMap((s) => [s.singer_group, s.duet_group]).filter(Boolean))]
    .sort((a, b) => a.localeCompare(b)), [songs]);

  const rows = useMemo(() => {
    const needle = q.trim().toLocaleLowerCase("en-CA");
    return songs.filter((s) => (!eventId || String(s.event_id) === eventId)
      && (!singer || s.singer_group === singer || s.duet_group === singer)
      && (!status || s.status === status || (status === "played" && s.status === "singing"))
      && (!from || isoDay(s.at) >= from) && (!to || isoDay(s.at) <= to)
      && (!needle || `${decodeEntities(s.title)} ${s.channel} ${s.singer} ${s.duet || ""} ${s.event} ${s.theme || ""}`
        .toLocaleLowerCase("en-CA").includes(needle)));
  }, [songs, q, eventId, singer, from, to, status]);

  const filtered = q || eventId || singer || from || to || status;
  const clear = () => { setQ(""); setEventId(""); setSinger(""); setFrom(""); setTo(""); setStatus(""); setShown(PAGE); };
  const hours = rows.reduce((t, r) => t + (r.status === "skipped" ? 0 : r.duration_s || 0), 0) / 3600;
  const nights = new Set(rows.map((r) => r.event_id)).size;
  const people = new Set(rows.flatMap((r) => [r.singer_group, r.duet_group]).filter(Boolean)).size;
  const topSingers = rank(rows, (r) => [r.singer_group, r.duet_group], (r, k) => k);
  const topSongs = rank(rows, songKey, (r) => decodeEntities(r.song));
  const perNight = rank(rows, (r) => String(r.event_id), (r) => `${r.event} · ${day(r.event_date)}`, 12);

  return (
    <div className="history">
      <div className="history-filters" role="search">
        <input type="search" placeholder="Search songs, singers, events…" value={q} aria-label="Search"
               onChange={(e) => { setQ(e.target.value); setShown(PAGE); }} />
        <select value={eventId} onChange={(e) => { setEventId(e.target.value); setShown(PAGE); }} aria-label="Event">
          <option value="">All events</option>
          {events.map((e) => <option key={e.id} value={e.id}>{e.name} · {day(e.date)}</option>)}
        </select>
        <select value={singer} onChange={(e) => { setSinger(e.target.value); setShown(PAGE); }} aria-label="Singer">
          <option value="">All singers</option>
          {singers.map((n) => <option key={n} value={n}>{n}</option>)}
        </select>
        <label className="date-field"><span>From</span>
          <input type="date" value={from} max={to || undefined} onChange={(e) => setFrom(e.target.value)} /></label>
        <label className="date-field"><span>To</span>
          <input type="date" value={to} min={from || undefined} onChange={(e) => setTo(e.target.value)} /></label>
        <select value={status} onChange={(e) => setStatus(e.target.value)} aria-label="Played or skipped">
          <option value="">Played and skipped</option>
          <option value="played">Played</option>
          <option value="skipped">Skipped</option>
        </select>
        {filtered && <button type="button" className="btn btn-link" onClick={clear}>Clear filters</button>}
      </div>

      <div className="stat-tiles">
        <div className="stat-tile"><b>{rows.length}</b><span>{rows.length === 1 ? "song" : "songs"}</span></div>
        <div className="stat-tile"><b>{people}</b><span>{people === 1 ? "singer" : "singers"}</span></div>
        <div className="stat-tile"><b>{nights}</b><span>{nights === 1 ? "event" : "events"}</span></div>
        <div className="stat-tile"><b>{hours < 10 ? hours.toFixed(1) : Math.round(hours)}</b><span>hours of music</span></div>
      </div>

      <div className="chart-grid">
        <BarList title="Top singers" rows={topSingers} empty="No songs yet." onPick={(k) => { setSinger(k); setShown(PAGE); }} />
        <BarList title="Most-sung songs" rows={topSongs} unit="time" empty="No songs yet."
                 onPick={(k) => { setQ(topSongs.find((r) => r[2] === k)?.[0] || ""); setShown(PAGE); }} />
        <BarList title="Songs per event" rows={perNight} empty="No events yet."
                 onPick={(k) => { setEventId(k); setShown(PAGE); }} />
      </div>

      <section className="history-list">
        <div className="history-list-head">
          <h3>{filtered ? `${rows.length} matching song${rows.length === 1 ? "" : "s"}` : "Every song, newest first"}</h3>
          <button type="button" className="btn" disabled={!rows.length} onClick={() => download(rows)}>
            ⬇ Export {filtered ? "these" : "all"} as CSV
          </button>
        </div>
        {rows.length === 0 ? (
          <p className="muted">{songs.length ? "No songs match these filters." : "Songs show up here once they've been sung."}</p>
        ) : (
          <div className="history-table" role="table" aria-label="Songs sung">
            <div className="h-row h-head" role="row">
              <span role="columnheader">When</span><span role="columnheader">Event</span>
              <span role="columnheader">Singer</span><span role="columnheader">Song</span>
              <span role="columnheader">Details</span>
            </div>
            {rows.slice(0, shown).map((r) => (
              <div key={r.id} className={`h-row ${r.status === "skipped" ? "skipped" : ""}`} role="row">
                <span role="cell" className="h-when">{day(r.at)}<small>{time(r.at)}</small></span>
                <span role="cell" className="h-event">{r.event}</span>
                <span role="cell" className="h-singer">
                  {r.singer_group}{r.duet_group && <small> &amp; {r.duet_group}</small>}
                  {r.singer_group !== r.singer.trim() && <small className="muted"> (as {r.singer})</small>}
                </span>
                <span role="cell" className="h-song">
                  <a href={`https://www.youtube.com/watch?v=${r.video_id}`} target="_blank" rel="noreferrer">
                    {decodeEntities(r.song)}</a>
                  {r.channel && <small className="muted">{r.channel}</small>}
                </span>
                <span role="cell" className="h-details">
                  {r.status === "skipped" && <span className="tag tag-skip">Skipped</span>}
                  {r.status === "singing" && <span className="tag">Singing now</span>}
                  {r.superset && <span className="tag tag-gold">★ Superset{r.theme ? `: ${r.theme}` : ""}</span>}
                  {!r.superset && r.theme && <span className="tag">{r.theme}</span>}
                  {r.cheers > 0 && <span className="tag">🔥 {r.cheers}</span>}
                </span>
              </div>
            ))}
          </div>
        )}
        {rows.length > shown && (
          <button type="button" className="btn btn-block" onClick={() => setShown(shown + PAGE)}>
            Show {Math.min(PAGE, rows.length - shown)} more ({rows.length - shown} left)
          </button>
        )}
      </section>
    </div>
  );
}
