import { useEffect, useMemo, useState } from "react";
import { api } from "../lib/api";
import HistoryDashboard from "../components/History";

/** Host admin: merge the names one singer has used across events. */
function SingerNames({ names, onChange, push }) {
  const [picked, setPicked] = useState([]);
  const [into, setInto] = useState("");
  const [filter, setFilter] = useState("");
  const [busy, setBusy] = useState(false);
  const shown = useMemo(() => {
    const f = filter.trim().toLocaleLowerCase("en-CA");
    return names.filter((n) => !f || `${n.name} ${n.group}`.toLocaleLowerCase("en-CA").includes(f));
  }, [names, filter]);
  const toggle = (name) => {
    const next = picked.includes(name) ? picked.filter((p) => p !== name) : [...picked, name];
    setPicked(next);
    // Suggest the name with the most songs as the one to keep.
    const top = names.filter((n) => next.includes(n.name)).sort((a, b) => b.songs - a.songs)[0];
    setInto(top ? top.group : "");
  };
  const call = async (path, body, done) => {
    setBusy(true);
    try { onChange(await api(path, { method: "POST", body })); done?.(); }
    catch (e) { push(e.message, "error"); } finally { setBusy(false); }
  };
  const merge = () => call("/api/host/history/merge", { names: picked, into }, () => {
    push(`Merged ${picked.length} names as ${into}.`, "success");
    setPicked([]);
    setInto("");
  });

  return (
    <details className="names-panel">
      <summary>Singer names ({names.length}) · merge names one person has used</summary>
      <p className="muted small">The same name with different capitals or spaces already counts as one singer. Tick the
        names that are really one person (e.g. “Al” and “Alan”), choose the name to show, and merge.</p>
      <div className="row wrap">
        <input type="search" placeholder="Find a name" value={filter} onChange={(e) => setFilter(e.target.value)} aria-label="Find a name" />
        <input value={into} onChange={(e) => setInto(e.target.value)} maxLength={24} placeholder="Show them as…" aria-label="Show them as" />
        <button className="btn btn-primary" disabled={busy || picked.length < 1 || !into.trim()} onClick={merge}>
          Merge {picked.length || ""} name{picked.length === 1 ? "" : "s"}
        </button>
      </div>
      <ul className="name-list">
        {shown.map((n) => (
          <li key={n.name}>
            <label className="check">
              <input type="checkbox" checked={picked.includes(n.name)} onChange={() => toggle(n.name)} />
              <span><strong>{n.name}</strong>{n.group !== n.name && <span className="muted"> → {n.group}</span>}
                <span className="muted small"> · {n.songs} song{n.songs === 1 ? "" : "s"}</span></span>
            </label>
            {n.merged && n.group !== n.name && (
              <button className="btn btn-link small" disabled={busy} onClick={() => call("/api/host/history/unmerge", { name: n.name })}>
                Unmerge</button>
            )}
          </li>
        ))}
      </ul>
    </details>
  );
}

/** Song history across every event, with the public page switch and name merging. */
export default function HistoryTab({ push }) {
  const [data, setData] = useState(null);
  const load = () => api("/api/host/history").then(setData).catch((e) => push(e.message, "error"));
  useEffect(() => { load(); }, []);
  const share = async (on) => {
    try {
      const r = await api("/api/host/history/public", { method: "PUT", body: { on } });
      setData({ ...data, public: r.public });
    } catch (e) { push(e.message, "error"); }
  };
  const url = `${window.location.origin}/history`;
  if (!data) return <section className="card"><p className="muted">Loading the song history…</p></section>;
  return (
    <section className="card">
      <h2>Song history</h2>
      <p className="muted">Every song sung (or skipped) at every event. Click a bar to filter. Deleting an event
        removes its songs from here too.</p>
      <label className="check">
        <input type="checkbox" checked={data.public} onChange={(e) => share(e.target.checked)} />
        <span>Share it with guests at <a href="/history" target="_blank" rel="noreferrer">{url}</a> (anyone with the
          link can see singers' names and songs)</span>
      </label>
      <SingerNames names={data.names} push={push} onChange={(names) => { setData({ ...data, names }); load(); }} />
      <HistoryDashboard songs={data.songs} />
    </section>
  );
}
