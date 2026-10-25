import { useEffect, useState } from "react";
import { api, guestSession } from "../lib/api";
import { decodeEntities } from "../lib/format";

const copy = (text, push) => navigator.clipboard?.writeText(text).then(() => push?.("Copied.", "success"), () => {});

/** Claim past nights: pick the names you sang under (honour system), or bring a code from another phone. */
export function ClaimSheet({ onClose, onChanged, push }) {
  const [groups, setGroups] = useState(null);
  const [picked, setPicked] = useState([]);
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => { api("/api/guest/claimable", { guest: true }).then(setGroups).catch((e) => push(e.message, "error")); }, [push]);

  const claim = async () => {
    setBusy(true);
    try {
      const r = await api("/api/guest/claim", { method: "POST", guest: true, body: { names: picked } });
      push(r.disputed
        ? `${r.claimed} night${r.claimed === 1 ? "" : "s"} added. ${r.disputed} already belonged to someone else: the host will decide.`
        : `${r.claimed} night${r.claimed === 1 ? "" : "s"} added to your singer code. 🎤`, r.disputed ? "warning" : "success", 9000);
      onChanged(r.singer);
      onClose();
    } catch (e) { push(e.message, "error"); } finally { setBusy(false); }
  };
  const useCode = async () => {
    setBusy(true);
    try {
      const r = await api("/api/guest/singer-code", { method: "POST", guest: true, body: { code } });
      push(`Welcome back, ${r.singer.name}! This phone now uses your singer code.`, "success");
      onChanged(r.singer);
      onClose();
    } catch (e) { push(e.message, "error"); } finally { setBusy(false); }
  };

  return (
    <section className="card claim-sheet">
      <div className="history-list-head"><h3>Claim your past nights</h3>
        <button className="btn btn-link" onClick={onClose}>Close</button></div>
      <p className="muted small">Tick the names you sang under. Every night under that name joins your singer code, so your
        songs, history and awards are all yours. Honour system: claim only your own!</p>
      {groups === null ? <p className="muted">Loading…</p> : !groups.length ? <p className="muted">No past nights yet.</p> : (
        <ul className="claim-list">
          {groups.map((g) => {
            const allMine = g.mine === g.nights;
            return (
              <li key={g.name}>
                <label className="check">
                  <input type="checkbox" disabled={allMine} checked={allMine || picked.includes(g.name)}
                         onChange={() => setPicked(picked.includes(g.name) ? picked.filter((p) => p !== g.name) : [...picked, g.name])} />
                  <span><strong>{g.name}</strong>
                    <span className="muted small"> · {g.nights} night{g.nights === 1 ? "" : "s"} · {g.songs} song{g.songs === 1 ? "" : "s"}
                      {g.events.length ? ` · ${g.events.join(", ")}${g.nights > g.events.length ? "…" : ""}` : ""}</span>
                    {allMine && <span className="pill">Yours</span>}
                    {g.others > 0 && <span className="claim-note">{g.others === g.nights ? "Linked" : `${g.others} linked`} to another
                      singer code: if it's you, the host will move {g.others === 1 ? "it" : "them"} after you claim</span>}
                  </span>
                </label>
              </li>
            );
          })}
        </ul>
      )}
      <button className="btn btn-primary btn-block" disabled={busy || !picked.length} onClick={claim}>
        Claim {picked.length || ""} name{picked.length === 1 ? "" : "s"}
      </button>
      <details className="small claim-code">
        <summary>Got a singer code on another phone?</summary>
        <div className="row">
          <input value={code} maxLength={6} placeholder="6 letters and numbers" aria-label="Singer code"
                 onChange={(e) => setCode(e.target.value.toUpperCase().replace(/[^A-Z0-9]/g, ""))} />
          <button className="btn" disabled={busy || code.length !== 6} onClick={useCode}>Use it</button>
        </div>
      </details>
    </section>
  );
}

/** Shown once after joining: your new code, and a nudge to claim past nights. */
export function SingerWelcome({ me, onClaim, onDismiss, onChanged, push }) {
  const [busy, setBusy] = useState(false);
  if (me.code_invalid) {
    const fresh = async () => {
      setBusy(true);
      try { const r = await api("/api/guest/singer/new", { method: "POST", guest: true }); onChanged(r.singer); onDismiss(); }
      catch (e) { push(e.message, "error"); } finally { setBusy(false); }
    };
    return (
      <section className="card singer-card">
        <h3>Your singer code was changed</h3>
        <p className="small">The host reset the code saved on this phone. Ask them for your new one, or start a new code.</p>
        <div className="row wrap">
          <button className="btn btn-primary" onClick={onClaim}>Enter my new code</button>
          <button className="btn" disabled={busy} onClick={fresh}>Start a new code</button>
        </div>
      </section>
    );
  }
  if (!me.new || !me.singer) return null;
  return (
    <section className="card singer-card">
      <button className="btn btn-link close-x" aria-label="Dismiss" onClick={onDismiss}>✕</button>
      <h3>🎤 Your singer code: <span className="singer-code">{me.singer.code}</span></h3>
      <p className="small">It's saved on this phone, so next time we'll know you. Keep it to use on another phone.
        <button className="btn btn-link small" onClick={() => copy(me.singer.code, push)}>Copy</button></p>
      {me.claimed > 0 && <p className="small">We found {me.claimed} past night{me.claimed === 1 ? "" : "s"} from this phone and added them.</p>}
      <p className="small"><strong>Sung here before?</strong> Claim your past nights so your songs count as yours.</p>
      <button className="btn btn-primary" onClick={onClaim}>Claim my past nights</button>
    </section>
  );
}

/** Your songs from past nights, one tap to add again. */
export function PastSongs({ onAdd, canAdd, push }) {
  const [songs, setSongs] = useState([]);
  const [adding, setAdding] = useState(null);
  useEffect(() => { api("/api/guest/past-songs", { guest: true }).then(setSongs).catch(() => {}); }, []);
  if (!songs.length) return null;
  const add = async (s) => {
    setAdding(s.video_id);
    try { await onAdd(s); } catch (e) { push(e.message, "error"); } finally { setAdding(null); }
  };
  return (
    <details className="card past-songs">
      <summary><strong>🎤 Your past songs ({songs.length})</strong> <span className="muted small">one tap to sing again</span></summary>
      <ul className="results">
        {songs.map((s) => (
          <li key={s.video_id} className="result">
            <div className="r-text">
              <div className="r-title">{decodeEntities(s.title)}</div>
              <div className="r-meta">{s.event_name}{s.times > 1 ? ` · sung ${s.times} times` : ""}</div>
            </div>
            <button className="btn btn-primary" disabled={!canAdd || adding === s.video_id} onClick={() => add(s)}>
              {adding === s.video_id ? "…" : "Add"}</button>
          </li>
        ))}
      </ul>
    </details>
  );
}

/** Footer line: your code, Copy, and Claim past nights. */
export function SingerFooter({ singer, onClaim, push }) {
  if (!singer) return null;
  return (
    <p className="rejoin-note small">Your singer code: <strong className="singer-code">{singer.code}</strong>
      <button className="btn btn-link small" onClick={() => copy(singer.code, push)}>Copy</button>
      <br /><span className="muted">Use it at any event, on any phone. {singer.nights} night{singer.nights === 1 ? "" : "s"} so far · </span>
      <button className="btn btn-link small" onClick={onClaim}>Claim past nights</button></p>
  );
}

export const rememberSinger = (singer) => guestSession.saveSinger(singer);
