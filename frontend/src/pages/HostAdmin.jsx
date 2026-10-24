import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../lib/api";
import { Toasts, useToasts } from "../components/Toasts";
import UpdatesTab from "./UpdatesTab";
import AppearanceTab from "./AppearanceTab";
import BackupsTab from "./BackupsTab";
import HistoryTab from "./HistoryTab";

const TABS = [["events", "Events"], ["history", "Song history"], ["themes", "Themes"], ["youtube", "YouTube"], ["appearance", "Appearance"], ["updates", "Updates"], ["backups", "Backups"], ["security", "Security"]];

function ThemesTab({ push }) {
  const [themes, setThemes] = useState([]);
  const blank = { name: "", description: "", ideas: "", weight: 1, enabled: true };
  const [draft, setDraft] = useState(blank);
  const [editing, setEditing] = useState(null);

  const load = () => api("/api/host/themes").then(setThemes).catch((e) => push(e.message, "error"));
  useEffect(() => { load(); }, []);

  const save = async (theme, id) => {
    try {
      await api(id ? `/api/host/themes/${id}` : "/api/host/themes", {
        method: id ? "PUT" : "POST",
        body: { ...theme, weight: Number(theme.weight) || 0,
          ideas: Array.isArray(theme.ideas) ? theme.ideas.join(", ") : theme.ideas || "" },
      });
      if (!id) setDraft(blank);
      setEditing(null);
      push(id ? "Theme saved." : "Theme added.", "success");
      load();
    } catch (e) {
      push(e.message, "error");
    }
  };

  const remove = async (t) => {
    if (!window.confirm(`Delete the theme “${t.name}”?`)) return;
    try { await api(`/api/host/themes/${t.id}`, { method: "DELETE" }); load(); } catch (e) { push(e.message, "error"); }
  };

  return (
    <section className="card">
      <h2>Themes</h2>
      <p className="muted">Themes are switched on per event (Host admin → Events). When they're on, each round spins one theme
        as a suggestion; when they're off, singers pick freely. Supersets spin from this list too. Weight makes a theme
        more (or less) likely to come up. Disabled themes are never spun. Search ideas show on phones as
        “Need ideas?” buttons.</p>
      <table className="table">
        <thead><tr><th>Name</th><th>Description</th><th>Search ideas</th><th>Weight</th><th>Enabled</th><th /></tr></thead>
        <tbody>
          {themes.map((t) => (editing?.id === t.id ? (
            <tr key={t.id}>
              <td data-label="Name"><input value={editing.name} maxLength={60} onChange={(e) => setEditing({ ...editing, name: e.target.value })} /></td>
              <td data-label="Description"><input value={editing.description} maxLength={280} onChange={(e) => setEditing({ ...editing, description: e.target.value })} /></td>
              <td data-label="Ideas"><input value={editing.ideas} maxLength={300} placeholder="Artists or songs, comma-separated"
                                             onChange={(e) => setEditing({ ...editing, ideas: e.target.value })} /></td>
              <td data-label="Weight"><input type="number" min="0" max="100" step="0.5" value={editing.weight}
                         onChange={(e) => setEditing({ ...editing, weight: e.target.value })} /></td>
              <td data-label="Enabled"><input type="checkbox" checked={editing.enabled} onChange={(e) => setEditing({ ...editing, enabled: e.target.checked })} /></td>
              <td className="actions">
                <button className="btn btn-primary" onClick={() => save(editing, t.id)}>Save</button>
                <button className="btn" onClick={() => setEditing(null)}>Cancel</button>
              </td>
            </tr>
          ) : (
            <tr key={t.id} className={t.enabled ? "" : "disabled"}>
              <td data-label="Name"><strong>{t.name}</strong></td>
              <td data-label="Description" className="muted">{t.description}</td>
              <td data-label="Ideas" className="muted small">{t.ideas.join(", ")}</td>
              <td data-label="Weight">{t.weight}</td>
              <td data-label="Enabled">
                <input type="checkbox" checked={t.enabled} aria-label={`Enable ${t.name}`}
                       onChange={(e) => save({ ...t, enabled: e.target.checked }, t.id)} />
              </td>
              <td className="actions">
                <button className="btn" onClick={() => setEditing({ ...t, ideas: t.ideas.join(", ") })}>Edit</button>
                <button className="btn btn-danger" onClick={() => remove(t)}>Delete</button>
              </td>
            </tr>
          )))}
        </tbody>
      </table>
      <h3>Add a theme</h3>
      <form className="row wrap" onSubmit={(e) => { e.preventDefault(); save(draft); }}>
        <input placeholder="Name, e.g. Disco" value={draft.name} maxLength={60} required
               onChange={(e) => setDraft({ ...draft, name: e.target.value })} />
        <input placeholder="Description (optional)" value={draft.description} maxLength={280}
               onChange={(e) => setDraft({ ...draft, description: e.target.value })} />
        <input placeholder="Search ideas, e.g. ABBA, Bee Gees (optional)" value={draft.ideas} maxLength={300}
               onChange={(e) => setDraft({ ...draft, ideas: e.target.value })} />
        <label className="inline">Weight
          <input type="number" min="0" max="100" step="0.5" value={draft.weight}
                 onChange={(e) => setDraft({ ...draft, weight: e.target.value })} />
        </label>
        <button className="btn btn-primary" disabled={!draft.name.trim()}>Add theme</button>
      </form>
    </section>
  );
}

function EventSettings({ eventId, push, onChanged }) {
  const [state, setState] = useState(null);
  const [cfg, setCfg] = useState(null);
  const [name, setName] = useState("");
  const [codes, setCodes] = useState({});

  const load = () => api(`/api/host/events/${eventId}/state`).then((s) => {
    setState(s);
    setCfg({ ...s.event.config, superset_chance: Math.round(s.event.config.superset_chance * 100) });
    setName(s.event.name);
    return api(`/api/host/events/${eventId}/guests`);
  }).then((gs) => setCodes(Object.fromEntries(gs.map((g) => [g.id, g.rejoin_code]))))
    .catch((e) => push(e.message, "error"));
  useEffect(() => { load(); }, [eventId]);

  if (!state || !cfg) return <p className="muted">Loading…</p>;

  const save = async (e) => {
    e.preventDefault();
    try {
      await api(`/api/host/events/${eventId}`, {
        method: "PATCH",
        body: {
          name,
          config: {
            ...cfg,
            superset_chance: Number(cfg.superset_chance) / 100,
            recent_theme_window: Number(cfg.recent_theme_window),
            max_duration_s: Number(cfg.max_duration_s),
            ready_seconds: Number(cfg.ready_seconds),
            superset_vote_seconds: Number(cfg.superset_vote_seconds),
            max_songs_per_singer: Number(cfg.max_songs_per_singer),
          },
        },
      });
      push("Event settings saved.", "success");
      load();
      onChanged();
    } catch (err) {
      push(err.message, "error");
    }
  };

  const guestAction = async (g, action) => {
    if (action === "remove" && !window.confirm(`Bouche ${g.name}? Their queued songs go too, and the TV lets everyone know.`)) return;
    try {
      await api(`/api/host/events/${eventId}/guests/${g.id}/${action}`, { method: "POST" });
      load();
    } catch (err) { push(err.message, "error"); }
  };

  const del = async () => {
    if (!window.confirm("Delete this event permanently? Its songs leave the Song history too. (Export them first if you want to keep them.)")) return;
    try { await api(`/api/host/events/${eventId}`, { method: "DELETE" }); onChanged(true); } catch (err) { push(err.message, "error"); }
  };

  const field = (key, label, props = {}) => (
    <label className="field">
      <span>{label}</span>
      <input {...props} value={cfg[key]} onChange={(e) => setCfg({ ...cfg, [key]: e.target.value })} />
    </label>
  );
  const toggle = (key, label) => (
    <label className="check">
      <input type="checkbox" checked={!!cfg[key]} onChange={(e) => setCfg({ ...cfg, [key]: e.target.checked })} />
      <span>{label}</span>
    </label>
  );

  return (
    <>
      <form className="card" onSubmit={save}>
        <h2>Settings for “{state.event.name}”</h2>
        <p className="muted small">Join code <strong>{state.event.join_code}</strong> · Status {state.event.status}
          {" "}· Round {state.round.number}</p>
        <div className="grid">
          <label className="field"><span>Event name</span>
            <input value={name} maxLength={80} onChange={(e) => setName(e.target.value)} /></label>
          {field("superset_chance", "Random Superset chance per round (%)", { type: "number", min: 0, max: 100 })}
          {field("recent_theme_window", "Avoid themes used in the last N rounds", { type: "number", min: 0, max: 20 })}
          {field("max_duration_s", "Longest video allowed (seconds, 0 = no limit)", { type: "number", min: 0, max: 3600 })}
          {field("ready_seconds", "“Get ready” countdown before each song (seconds, 0 = off)", { type: "number", min: 0, max: 60 })}
          {field("max_songs_per_singer", "Songs each singer can have waiting (0 = no limit)", { type: "number", min: 0, max: 50 })}
          {field("superset_vote_seconds", "How long a singer's Superset vote stays open (seconds)", { type: "number", min: 15, max: 300 })}
          {field("last_call", "Last call: closing time (blank = none). Songs that would run past it are refused.", { type: "time" })}
          <label className="field"><span>Safe search</span>
            <select value={cfg.safe_search} onChange={(e) => setCfg({ ...cfg, safe_search: e.target.value })}>
              <option value="none">Off</option>
              <option value="moderate">Moderate</option>
              <option value="strict">Strict</option>
            </select>
          </label>
        </div>
        {toggle("themes_enabled", "Themes: spin a theme each round as a suggestion (off: singers pick freely)")}
        {toggle("prevent_duplicates", "Prevent the same song twice in one event")}
        {toggle("autoplay", "Start playing automatically when the first song is queued")}
        <div className="row wrap">
          <button className="btn btn-primary">Save settings</button>
          <Link className="btn" to={`/host/event/${eventId}`}>Open TV screen</Link>
          <Link className="btn" to={`/host/remote/${eventId}`}>📱 Phone remote</Link>
          <a className="btn" href={`/api/host/events/${eventId}/history.csv`}>Export song history (CSV)</a>
          <span className="spacer" />
          <button type="button" className="btn btn-danger" onClick={del}>Delete event</button>
        </div>
      </form>

      <section className="card">
        <h2>Singer order ({state.guests.length})</h2>
        <p className="muted small">Songs play one per singer per round, in this order. New singers who join mid-event
          go to the end of the order. A singer who switches phones can rejoin with the code shown
          beside their name.</p>
        {!state.guests.length && <p className="muted">Nobody has joined yet.</p>}
        <ol className="list">
          {state.guests.map((g, idx) => (
            <li key={g.id} className="list-row">
              <span>
                <strong>{g.name}</strong>
                {state.now_playing?.guest_id === g.id && <span className="pill">Singing</span>}
                {g.new_singer && <span className="pill">New singer</span>}
                <span className="muted small"> · {g.queued} queued</span>
                {codes[g.id] && <span className="muted small" title="Rejoin code: lets this singer switch phones"> · rejoin <code>{codes[g.id]}</code></span>}
              </span>
              <span className="actions">
                <button className="btn" title="Earlier in the order" disabled={idx === 0}
                        onClick={() => guestAction(g, "up")}>▲</button>
                <button className="btn" title="Later in the order" disabled={idx === state.guests.length - 1}
                        onClick={() => guestAction(g, "down")}>▼</button>
                <button className="btn btn-danger" title="Remove this singer from the event" onClick={() => guestAction(g, "remove")}>Bouche!</button>
              </span>
            </li>
          ))}
        </ol>
      </section>

      <section className="card">
        <h2>Themes and Supersets</h2>
        {!cfg.themes_enabled && <p className="muted small">Themes are off: singers pick freely. Supersets still spin a
          theme (or take one from the song that kicks them off).</p>}
        {state.rounds.length > 0 && (
          <ul className="list compact">
            {state.rounds.map((r) => <li key={r.number}>Round {r.number}: <strong>{r.theme}</strong></li>)}
          </ul>
        )}
        {state.superset_history.length > 0 && (
          <ul className="list compact">
            {state.superset_history.map((x, n) => (
              <li key={n}>★ Superset: <strong>{x.theme}</strong>
                <span className="pill">{{ vote: "voted in", host: "by the host", random: "random" }[x.source]}</span>
                {x.status !== "done" && <span className="pill">{x.status === "active" ? "under way" : "cancelled"}</span>}</li>
            ))}
          </ul>
        )}
        {!state.rounds.length && !state.superset_history.length && <p className="muted">Nothing yet.</p>}
      </section>
    </>
  );
}

function EventsTab({ push }) {
  const [events, setEvents] = useState([]);
  const [selected, setSelected] = useState(null);
  const load = (clear) => api("/api/host/events").then((evs) => {
    setEvents(evs);
    if (clear || !selected) setSelected(evs[0]?.id ?? null);
  }).catch((e) => push(e.message, "error"));
  useEffect(() => { load(); }, []);

  return (
    <>
      <section className="card">
        <h2>Events</h2>
        {!events.length && <p className="muted">No events yet. <Link to="/host">Create one</Link>.</p>}
        <div className="row wrap">
          {events.map((ev) => (
            <button key={ev.id} className={`btn ${selected === ev.id ? "btn-primary" : ""}`} onClick={() => setSelected(ev.id)}>
              {ev.name} <span className="muted small">({ev.status})</span>
            </button>
          ))}
        </div>
      </section>
      {selected && <EventSettings key={selected} eventId={selected} push={push} onChanged={load} />}
    </>
  );
}

function YouTubeTab({ push }) {
  const [q, setQ] = useState(null);
  useEffect(() => { api("/api/host/quota").then(setQ).catch((e) => push(e.message, "error")); }, []);
  if (!q) return <section className="card"><p className="muted">Loading…</p></section>;
  const pct = q.daily_quota ? Math.round((q.units_remaining / q.daily_quota) * 100) : 0;
  return (
    <section className="card">
      <h2>YouTube search</h2>
      <p>Search mode: <strong>{{ api: "YouTube Data API", ytdlp: "Backup search (yt-dlp metadata only)", unavailable: "Unavailable" }[q.mode]}</strong></p>
      {!q.api_key_configured && <p className="warning">No YOUTUBE_API_KEY is set. Searches use the backup search, which is slower.</p>}
      {q.api_key_configured && (
        <>
          <div className="meter"><div style={{ width: `${pct}%` }} /></div>
          <p>Estimated quota left today: <strong>{q.units_remaining.toLocaleString("en-CA")}</strong> of {q.daily_quota.toLocaleString("en-CA")} units
            {" "}(about {q.searches_remaining} new searches). Resets at midnight Pacific time.</p>
          {q.exhausted && <p className="warning">YouTube reported the daily quota is used up. Backup search is in use until it resets.</p>}
          <p className="muted small">Each new search costs about 101 units. Repeat searches within 24 hours come from the cache and are free.</p>
        </>
      )}
    </section>
  );
}

function SecurityTab({ push }) {
  const [session, setSession] = useState(null);
  const [form, setForm] = useState({ current: "", new: "", confirm: "" });
  useEffect(() => { api("/api/host/session").then(setSession); }, []);
  const submit = async (e) => {
    e.preventDefault();
    if (form.new !== form.confirm) { push("The new PINs don't match.", "error"); return; }
    try {
      await api("/api/host/pin", { method: "POST", body: { current: form.current, new: form.new } });
      setForm({ current: "", new: "", confirm: "" });
      push("Host PIN updated.", "success");
    } catch (err) { push(err.message, "error"); }
  };
  const logout = async () => { await api("/api/host/logout", { method: "POST" }); window.location.href = "/host"; };
  return (
    <section className="card">
      <h2>Host PIN</h2>
      {session?.pin_from_env ? (
        <p className="muted">The PIN is set by <code>HOST_PIN</code> in your <code>.env</code> file. Edit it there and run <code>./update.sh</code>.</p>
      ) : (
        <form className="narrow" onSubmit={submit}>
          {["current", "new", "confirm"].map((k) => (
            <label key={k} className="field"><span>{{ current: "Current PIN", new: "New PIN (4+ characters)", confirm: "Confirm new PIN" }[k]}</span>
              <input type="password" value={form[k]} minLength={k === "current" ? 1 : 4} maxLength={64} required
                     onChange={(e) => setForm({ ...form, [k]: e.target.value })} /></label>
          ))}
          <button className="btn btn-primary">Change PIN</button>
        </form>
      )}
      <hr />
      <button className="btn" onClick={logout}>Sign out of host admin</button>
      <p className="muted small">Karoulette v{session?.version}</p>
    </section>
  );
}

export default function HostAdmin() {
  const [tab, setTab] = useState("events");
  const [info, setInfo] = useState({ version: null, update: null });
  const { toasts, push } = useToasts();
  useEffect(() => {
    api("/api/host/session").then((s) => setInfo((i) => ({ ...i, version: s.version }))).catch(() => {});
    api("/api/host/updates")
      .then((u) => setInfo((i) => ({ ...i, update: u.update_available ? u.latest.version : null })))
      .catch(() => {});
  }, []);
  return (
    <main className="page">
      <header className="page-header">
        <h1 className="brand small">
          Kar<span>oulette</span> <span className="muted">admin</span>
          {info.version && <span className="version-tag" title="Running version">v{info.version}</span>}
          {info.update && (
            <button className="version-tag update" onClick={() => setTab("updates")}>v{info.update} available</button>
          )}
        </h1>
        <Link className="btn" to="/host">Back to events</Link>
      </header>
      <nav className="tabs">
        {TABS.map(([k, label]) => (
          <button key={k} className={`tab ${tab === k ? "active" : ""}`} onClick={() => setTab(k)}>{label}</button>
        ))}
      </nav>
      {tab === "events" && <EventsTab push={push} />}
      {tab === "history" && <HistoryTab push={push} />}
      {tab === "themes" && <ThemesTab push={push} />}
      {tab === "youtube" && <YouTubeTab push={push} />}
      {tab === "appearance" && <AppearanceTab push={push} />}
      {tab === "updates" && <UpdatesTab push={push} loadedVersion={info.version} />}
      {tab === "backups" && <BackupsTab push={push} />}
      {tab === "security" && <SecurityTab push={push} />}
      <Toasts toasts={toasts} />
    </main>
  );
}
