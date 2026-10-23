import { useEffect, useRef, useState } from "react";
import { api } from "../lib/api";

const KINDS = { manual: "Made here", "pre-update": "Before an upgrade", "pre-restore": "Before a restore", uploaded: "Uploaded" };

function size(bytes) {
  return bytes > 1_000_000 ? `${(bytes / 1_000_000).toFixed(1)} MB` : `${Math.max(1, Math.round(bytes / 1000))} KB`;
}

/** Download, keep and restore copies of the database. */
export default function BackupsTab({ push }) {
  const [data, setData] = useState(null);
  const [busy, setBusy] = useState(false);
  const fileRef = useRef(null);
  const load = () => api("/api/host/backups").then(setData).catch((e) => push(e.message, "error"));
  useEffect(() => { load(); }, []);

  const make = async () => {
    setBusy(true);
    try {
      const b = await api("/api/host/backups", { method: "POST" });
      push("Backup made.", "success");
      window.location.href = `/api/host/backups/${encodeURIComponent(b.name)}`;
      load();
    } catch (e) { push(e.message, "error"); } finally { setBusy(false); }
  };

  const restored = (r) => {
    push(`Restored. The database from before is saved as ${r.safety_backup}.`, "success", 9000);
    load();
  };

  const restore = async (name) => {
    if (!window.confirm(`Restore ${name}? Everything (events, singers, songs, themes and settings) goes back to that `
      + "copy. The current database is saved first, so you can undo this.")) return;
    setBusy(true);
    try { restored(await api(`/api/host/backups/${encodeURIComponent(name)}/restore`, { method: "POST" })); }
    catch (e) { push(e.message, "error"); } finally { setBusy(false); }
  };

  const upload = async (file) => {
    if (!file || !window.confirm(`Restore from ${file.name}? The current database is saved first.`)) return;
    setBusy(true);
    try {
      const res = await fetch("/api/host/backups-upload", { method: "POST", body: file, credentials: "same-origin",
        headers: { "Content-Type": "application/octet-stream" } });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(body.detail || `Upload failed (${res.status})`);
      restored(body);
    } catch (e) { push(e.message, "error"); } finally { setBusy(false); if (fileRef.current) fileRef.current.value = ""; }
  };

  const remove = async (name) => {
    if (!window.confirm(`Delete the backup ${name}?`)) return;
    try { await api(`/api/host/backups/${encodeURIComponent(name)}`, { method: "DELETE" }); load(); }
    catch (e) { push(e.message, "error"); }
  };

  return (
    <section className="card">
      <h2>Backups</h2>
      <p className="muted">A backup is a copy of the whole database: events, singers, songs, themes and settings. One is
        made automatically before every upgrade. They're kept in <code>{data?.folder || "backups"}</code> in your data
        folder (the last 10 of each kind).</p>
      <div className="row wrap">
        <button className="btn btn-primary" disabled={busy} onClick={make}>⬇ Make and download a backup</button>
        <label className={`btn ${busy ? "disabled" : ""}`}>
          ⬆ Restore from a file…
          <input ref={fileRef} type="file" accept=".db,application/vnd.sqlite3,application/octet-stream" hidden
                 disabled={busy} onChange={(e) => upload(e.target.files[0])} />
        </label>
      </div>
      {!data && <p className="muted">Loading…</p>}
      {data && !data.backups.length && <p className="muted">No backups yet.</p>}
      {data?.backups.length > 0 && (
        <ul className="list">
          {data.backups.map((b) => (
            <li key={b.name} className="list-row">
              <span>
                <strong>{new Date(b.created_at * 1000).toLocaleString("en-CA")}</strong>
                <span className="pill">{KINDS[b.kind] || b.kind}</span>
                <div className="muted small">{b.name} · {size(b.size)}</div>
              </span>
              <span className="actions">
                <a className="btn" href={`/api/host/backups/${encodeURIComponent(b.name)}`}>Download</a>
                <button className="btn" disabled={busy} onClick={() => restore(b.name)}>Restore</button>
                <button className="btn btn-danger" disabled={busy} onClick={() => remove(b.name)}>Delete</button>
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
