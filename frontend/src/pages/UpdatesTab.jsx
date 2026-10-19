import { useCallback, useEffect, useState } from "react";
import { api } from "../lib/api";

const AGENT = "sudo ./scripts/upgrade-agent.sh --install";

function when(iso) {
  if (!iso) return null;
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? null : d.toLocaleString("en-CA", { dateStyle: "medium", timeStyle: "short" });
}

/** Just enough Markdown for CHANGELOG notes: ### headings, - bullets, **bold** stays as text. */
function Notes({ text }) {
  const blocks = [];
  let list = null;
  text.split("\n").forEach((raw, i) => {
    const line = raw.trimEnd();
    if (/^\s*[-*] /.test(line)) {
      if (!list) { list = []; blocks.push(<ul key={`u${i}`}>{list}</ul>); }
      list.push(<li key={i}>{line.replace(/^\s*[-*] /, "")}</li>);
      return;
    }
    list = null;
    if (/^#{1,6} /.test(line)) blocks.push(<h4 key={i}>{line.replace(/^#{1,6} /, "")}</h4>);
    else if (line.trim()) blocks.push(<p key={i}>{line}</p>);
  });
  return <div className="notes">{blocks.length ? blocks : "No release notes."}</div>;
}

function Copyable({ value, push }) {
  return (
    <span className="copy-row">
      <code>{value}</code>
      <button type="button" className="btn" onClick={async () => {
        try { await navigator.clipboard.writeText(value); push("Copied.", "success"); }
        catch { push("Couldn't copy. Select the text instead.", "error"); }
      }}>Copy</button>
    </span>
  );
}

/** This version, the latest release, and upgrades run by the helper on the server (as in Glasshaus). */
export default function UpdatesTab({ push, loadedVersion }) {
  const [s, setS] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [restarting, setRestarting] = useState(false);

  const load = useCallback(async () => {
    try {
      setS(await api("/api/host/updates"));
      setRestarting(false);
      setError("");
    } catch (e) {
      // While an upgrade restarts the server, a failed poll just means "still restarting".
      setRestarting(true);
      setError(e.message);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const running = s?.upgrade?.state === "requested" || s?.upgrade?.state === "running";
  useEffect(() => {
    if (!running && !restarting) return undefined;
    const t = setInterval(load, 4000);
    return () => clearInterval(t);
  }, [running, restarting, load]);

  const check = async () => {
    setBusy(true);
    try {
      const data = await api("/api/host/updates/check", { method: "POST" });
      setS(data);
      push(data.update_available ? `KaraokeQueue ${data.latest.version} is available.` : "KaraokeQueue is up to date.",
        data.update_available ? "gold" : "success");
    } catch (e) { push(e.message, "error"); } finally { setBusy(false); }
  };

  const upgrade = async () => {
    const v = s.latest.version;
    if (!window.confirm(`Upgrade to ${v}? The database is backed up first. The TV and phones show "reconnecting" for a minute while it restarts, then the event carries on. If anything fails it goes back to this version.`)) return;
    setBusy(true);
    try {
      setS(await api("/api/host/updates/upgrade", { method: "POST", body: { version: v } }));
      push("Upgrade requested. The server starts it at its next check.", "success");
    } catch (e) { push(e.message, "error"); } finally { setBusy(false); }
  };

  if (!s) {
    return <section className="card">{error ? <p className="error">{error}</p> : <p className="muted">Loading…</p>}</section>;
  }
  const u = s.upgrade;

  return (
    <section className="card">
      <h2>Updates</h2>
      <p className="muted">KaraokeQueue checks once a day for a new release. You can upgrade from here: a helper on
        the server backs up the database, rebuilds, checks the new version is healthy, and goes back to this
        version if anything fails.</p>

      <dl className="facts">
        <dt>This server</dt><dd>{s.current}</dd>
        <dt>Latest release</dt>
        <dd>{s.latest ? <>{s.latest.version}{when(s.latest.published_at) && ` (${when(s.latest.published_at)})`}</> : "Not checked yet"}</dd>
        <dt>Last checked</dt>
        <dd>{when(s.checked_at) || "Never"}{s.check_error && <span className="warning"> (failed: {s.check_error})</span>}</dd>
      </dl>

      <div className="row wrap">
        <button className="btn" onClick={check} disabled={busy}>{busy ? "Checking…" : "Check now"}</button>
        {!s.update_available && s.latest && <span className="success">✓ KaraokeQueue is up to date.</span>}
      </div>

      {(running || restarting) && (
        <div className="status-box" role="status">
          <strong>
            {restarting ? "KaraokeQueue is restarting with the new version…"
              : u.state === "requested" ? `Upgrade to ${u.to_version} requested. The server starts it at its next check.`
                : `Upgrading to ${u.to_version}… This takes a few minutes; you can leave this page.`}
          </strong>
          {u?.state === "requested" && !s.helper.connected && (
            <p>The upgrade helper hasn't checked in lately, so nothing will start until it runs. On the server, run
              {" "}<code>sudo ./scripts/upgrade-agent.sh</code> once, or reinstall its schedule.</p>
          )}
        </div>
      )}
      {u?.state === "succeeded" && (
        <p className="success" role="status">
          {u.message || "Upgraded."}{" "}
          {u.to_version && u.to_version !== loadedVersion && (
            <button className="btn" onClick={() => window.location.reload()}>Reload to use it</button>
          )}
        </p>
      )}
      {u?.state === "failed" && <p className="error" role="alert">{u.message || "The upgrade stopped."}</p>}

      {s.update_available && s.latest && (
        <section className="card" aria-labelledby="release-notes">
          <h3 id="release-notes">What's new in {s.latest.version}</h3>
          <Notes text={s.latest.notes || ""} />
          <p><a href={s.latest.url} target="_blank" rel="noreferrer">Release page</a></p>
          {s.helper.connected ? (
            <button className="btn btn-primary btn-xl" disabled={!s.can_upgrade || busy} onClick={upgrade}>
              Upgrade to {s.latest.version}
            </button>
          ) : (
            <div>
              <p>To upgrade from here, set up the upgrade helper on the server once. It runs every 15 minutes and only
                acts when you press Upgrade. On TrueNAS it adds a cron job under System › Advanced Settings. In the
                KaraokeQueue folder on the server, run:</p>
              <Copyable value={AGENT} push={push} />
              <p className="muted small">
                {s.helper.configured
                  ? s.helper.last_seen
                    ? `The helper last checked in ${when(s.helper.last_seen)}; it should run every ${s.helper.every_minutes} minute(s).`
                    : "The helper hasn't checked in yet."
                  : "This server has no upgrade folder yet; the command creates it (then restart with ./update.sh --no-git)."}
                {" "}Or upgrade from a terminal with <code>./update.sh</code>.
              </p>
            </div>
          )}
        </section>
      )}

      {s.log && (
        <details open={running}>
          <summary>Upgrade log</summary>
          <pre className="log">{s.log}</pre>
        </details>
      )}
    </section>
  );
}
