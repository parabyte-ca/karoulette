import { useEffect, useMemo, useState } from "react";
import { api } from "../lib/api";
import HistoryDashboard from "../components/History";
import { resetPlaylistConfig } from "../lib/playlists";

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

/** Host admin: connect a Spotify app so people can save playlists to their own Spotify. */
function SpotifySetup({ spotify, push, onSaved }) {
  const [id, setId] = useState(spotify.client_id);
  const [busy, setBusy] = useState(false);
  const redirect = spotify.redirect_uri || `${window.location.origin}/spotify`;
  const save = async (value) => {
    setBusy(true);
    try {
      const r = await api("/api/host/playlists/spotify", { method: "PUT", body: { client_id: value } });
      resetPlaylistConfig();
      onSaved(r.spotify_client_id);
      push(r.spotify_client_id ? "Spotify playlists are on." : "Spotify playlists are off.", "success");
    } catch (e) { push(e.message, "error"); } finally { setBusy(false); }
  };
  return (
    <details className="names-panel">
      <summary>Playlists · Spotify {spotify.client_id ? "connected ✓" : "not set up (YouTube playlists work already)"}</summary>
      <p className="muted small">YouTube playlists need nothing set up. For Spotify, connect a free Spotify developer app
        once; then each person signs in with their own Spotify and the playlist is saved to their account.</p>
      <ol className="small setup-steps">
        <li>Go to <a href="https://developer.spotify.com/dashboard" target="_blank" rel="noreferrer">developer.spotify.com/dashboard</a>
          , sign in and choose <strong>Create app</strong> (any name, e.g. Karoulette).</li>
        <li>Add this <strong>Redirect URI</strong> exactly: <code>{redirect}</code>
          <button type="button" className="btn btn-link small" onClick={() => navigator.clipboard?.writeText(redirect)}>Copy</button>
          <br /><span className="muted">It must be the HTTPS address guests use. Add one for each address if you have several.</span></li>
        <li>Tick <strong>Web API</strong>, save, then copy the app's <strong>Client ID</strong> here.</li>
        <li>While the app is in Spotify's development mode, only the Spotify accounts you add under
          <strong> User Management</strong> can sign in. Ask Spotify for an extension to open it to everyone.</li>
      </ol>
      {spotify.from_env ? <p className="small">Set by <code>SPOTIFY_CLIENT_ID</code> in the container settings.</p> : (
        <div className="row wrap">
          <input value={id} onChange={(e) => setId(e.target.value.trim())} placeholder="Spotify Client ID" aria-label="Spotify Client ID" maxLength={64} />
          <button className="btn btn-primary" disabled={busy || id === spotify.client_id} onClick={() => save(id)}>Save</button>
          {spotify.client_id && <button className="btn btn-danger" disabled={busy} onClick={() => { setId(""); save(""); }}>Turn off</button>}
        </div>
      )}
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
      <SpotifySetup spotify={data.spotify} push={push}
                    onSaved={(clientId) => setData({ ...data, spotify: { ...data.spotify, client_id: clientId } })} />
      <HistoryDashboard songs={data.songs} />
    </section>
  );
}
