import { useEffect, useState } from "react";
import { api } from "../lib/api";

const day = (t) => new Date(t * 1000).toLocaleDateString("en-CA", { year: "numeric", month: "short", day: "numeric" });
const HOW = { phone: "this phone was there", name: "claimed by name", host: "set by the host" };
const OWNER_HOW = { phone: "their phone was there", name: "they claimed it by name", host: "you gave it to them" };

/** Host admin → Song history: singer codes, the nights each owns, disputes, and moving nights by hand. */
export default function SingersAdmin({ push, onChanged }) {
  const [data, setData] = useState(null);
  const [busy, setBusy] = useState(false);
  const load = () => api("/api/host/singers").then(setData).catch((e) => push(e.message, "error"));
  useEffect(() => { load(); }, []);
  const call = async (path, body, msg) => {
    setBusy(true);
    try { setData(await api(path, { method: "POST", body })); if (msg) push(msg, "success"); onChanged?.(); }
    catch (e) { push(e.message, "error"); } finally { setBusy(false); }
  };
  if (!data) return null;
  const options = data.singers.map((s) => <option key={s.id} value={s.id}>{s.name} ({s.code})</option>);
  const move = (guestId, value) => call("/api/host/singers/assign",
    { guest_id: guestId, singer_id: value === "" ? null : Number(value) }, value === "" ? "Night unclaimed." : "Night moved.");
  const night = (n, current) => (
    <li key={n.guest_id}>
      <span><strong>{n.event_name}</strong> <span className="muted small">· {day(n.event_date)} · as {n.name} · {n.songs} song{n.songs === 1 ? "" : "s"}
        {n.claimed_how ? ` · ${HOW[n.claimed_how]}` : ""}</span></span>
      <select value={current ?? ""} disabled={busy} aria-label={`Who sang as ${n.name} at ${n.event_name}`}
              onChange={(e) => move(n.guest_id, e.target.value)}>
        <option value="">{current ? "Unclaim" : "Give to…"}</option>
        {options}
      </select>
    </li>
  );

  return (
    <details className="names-panel" open={data.disputes.length > 0}>
      <summary>Singers and codes ({data.singers.length}){data.disputes.length ? ` · ${data.disputes.length} to decide` : ""}</summary>
      <p className="muted small">Each singer code owns the nights claimed by its phone, by name, or by you. A claim on a night
        someone else owns waits here for you to decide. You can also move any night, or reset a code that was shared or lost.</p>

      {data.disputes.length > 0 && (
        <>
          <h4>To decide</h4>
          <ul className="name-list disputes">
            {data.disputes.map((d) => (
              <li key={d.id}>
                <span><strong>{d.claimant}</strong> <code>{d.claimant_code}</code> claims <strong>{d.name}</strong> at {d.event_name}
                  <span className="muted small"> · {day(d.event_date)} · belongs to {d.owner} <code>{d.owner_code}</code>
                    {d.owner_how ? ` (${OWNER_HOW[d.owner_how]})` : ""}</span>
                  {d.how === "phone" && <span className="pill">{d.claimant}'s phone was there</span>}</span>
                <span className="actions">
                  <button className="btn btn-primary" disabled={busy} onClick={() => call(`/api/host/singer-claims/${d.id}`, { approve: true }, `Moved to ${d.claimant}.`)}>Give to {d.claimant}</button>
                  <button className="btn" disabled={busy} onClick={() => call(`/api/host/singer-claims/${d.id}`, { approve: false }, `Kept with ${d.owner}.`)}>Keep</button>
                </span>
              </li>
            ))}
          </ul>
        </>
      )}

      <h4>Singers</h4>
      {!data.singers.length && <p className="muted small">No singer codes yet: phones get one when they next join.</p>}
      <ul className="singer-list">
        {data.singers.map((s) => (
          <li key={s.id}>
            <details>
              <summary><strong>{s.name}</strong> <code>{s.code}</code>
                <span className="muted small"> · {s.nights.length} night{s.nights.length === 1 ? "" : "s"}</span></summary>
              <ul className="night-list">{s.nights.map((n) => night(n, s.id))}</ul>
              <button className="btn btn-link small" disabled={busy} onClick={() =>
                window.confirm(`Reset ${s.name}'s singer code? Their phone will be asked for the new one.`)
                && call(`/api/host/singers/${s.id}/reset-code`, undefined, "New code made.")}>Reset code</button>
            </details>
          </li>
        ))}
      </ul>

      {data.unclaimed.length > 0 && (
        <>
          <h4>Unclaimed nights ({data.unclaimed.length})</h4>
          <ul className="night-list">{data.unclaimed.map((n) => night(n, null))}</ul>
        </>
      )}
    </details>
  );
}
