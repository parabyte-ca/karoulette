import { useCallback, useEffect, useState } from "react";
import { api } from "../lib/api";
import { decodeEntities, formatDuration } from "../lib/format";

const day = (t) => new Date(t * 1000).toLocaleDateString("en-CA", { year: "numeric", month: "short", day: "numeric" });

/** ❤️ on someone else's song. Likes are just love: they never move a song. */
export function LikeButton({ item, myId, push }) {
  const [busy, setBusy] = useState(false);
  const liked = (item.liked_by || []).includes(myId);
  const toggle = async () => {
    setBusy(true);
    try { await api(`/api/guest/like/${item.id}`, { method: "POST", guest: true }); }
    catch (e) { push(e.message, "error"); } finally { setBusy(false); }
  };
  return (
    <button className={`btn like-btn ${liked ? "liked" : ""}`} aria-pressed={liked} disabled={busy} onClick={toggle}
            title={liked ? "Unlike" : "Like this song"} aria-label={`${liked ? "Unlike" : "Like"} ${decodeEntities(item.title)}`}>
      {liked ? "❤️" : "🤍"}{item.likes > 0 ? ` ${item.likes}` : ""}
    </button>
  );
}

/** Songs other guests suggested for you: add with one tap, or pass. `bump` changes when a new one arrives. */
export function Suggestions({ bump, canAdd, push }) {
  const [list, setList] = useState([]);
  const [busy, setBusy] = useState(null);
  const load = useCallback(() => api("/api/guest/suggestions", { guest: true }).then(setList).catch(() => {}), []);
  useEffect(() => { load(); }, [load, bump]);
  if (!list.length) return null;
  const act = async (r, what) => {
    setBusy(r.id);
    try {
      await api(`/api/guest/suggestions/${r.id}/${what}`, { method: "POST", guest: true });
      if (what === "add") push(`Added! 🎶 ${r.from} will be thrilled.`, "success");
    } catch (e) { push(e.message, "error"); } finally { setBusy(null); load(); }
  };
  return (
    <section className="card suggestions">
      <h3>🎁 Suggested for you</h3>
      <ul className="results">
        {list.map((r) => (
          <li key={r.id} className="result">
            <img src={r.thumbnail || `https://i.ytimg.com/vi/${r.video_id}/mqdefault.jpg`} alt="" loading="lazy" />
            <div className="r-text">
              <div className="r-title">{decodeEntities(r.title)}</div>
              <div className="r-meta">From {r.from}{r.duration_s ? ` · ${formatDuration(r.duration_s)}` : ""}</div>
            </div>
            <div className="song-actions">
              <button className="btn btn-primary" disabled={!canAdd || busy === r.id} onClick={() => act(r, "add")}>Add</button>
              <button className="btn" disabled={busy === r.id} title="No thanks" aria-label="No thanks"
                      onClick={() => act(r, "dismiss")}>✕</button>
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}

/** A singer's own records on their phone, with anything they beat tonight. */
export function MyBests({ refresh }) {
  const [a, setA] = useState(null);
  useEffect(() => { api("/api/guest/awards", { guest: true }).then((r) => setA(r.awards)).catch(() => {}); }, [refresh]);
  if (!a) return null;
  return (
    <details className="card my-bests" open={a.tonight.length > 0}>
      <summary><strong>🏅 Your personal bests</strong> <span className="muted small">{a.nights} night{a.nights === 1 ? "" : "s"} · {a.songs} song{a.songs === 1 ? "" : "s"}</span></summary>
      {a.tonight.length > 0 && <ul className="bests-new">{a.tonight.map((t) => <li key={t}>{t}</li>)}</ul>}
      <dl className="bests">
        <div><dt>Most songs in a night</dt><dd>{a.best_night.songs} at {a.best_night.event}</dd></div>
        {a.top_song && <div><dt>Most-cheered song</dt><dd>{decodeEntities(a.top_song.title)} ({a.top_song.cheers} cheers)</dd></div>}
        {a.favourite && <div><dt>Your go-to song</dt><dd>{decodeEntities(a.favourite.song)} (sung {a.favourite.times} times)</dd></div>}
        {a.streak > 1 && <div><dt>Longest streak</dt><dd>{a.streak} nights in a row</dd></div>}
        {a.cheers > 0 && <div><dt>Cheers, all time</dt><dd>{a.cheers}</dd></div>}
        <div><dt>First night</dt><dd>{a.first_night.event} · {day(a.first_night.date)}</dd></div>
      </dl>
    </details>
  );
}

/** The Awards board (Song history and /history): regulars, perfect attendance, streaks, records, newcomers. */
export function AwardsBoard({ awards }) {
  if (!awards || !awards.nights) return null;
  const { regulars, perfect_attendance: perfect, streaks, records, newcomers } = awards;
  return (
    <section className="awards" aria-label="Awards">
      <h3>🏆 Awards <span className="muted small">across {awards.nights} night{awards.nights === 1 ? "" : "s"}</span></h3>
      <div className="awards-grid">
        {records.length > 0 && (
          <div className="award-card">
            <h4>All-time records</h4>
            <ul>{records.map((r) => <li key={r.award}><b>{r.award}</b><span>{decodeEntities(r.holder)}</span><small className="muted">{r.value}</small></li>)}</ul>
          </div>
        )}
        {regulars.length > 0 && (
          <div className="award-card">
            <h4>Regulars</h4>
            <ol>{regulars.map((r) => <li key={r.name}><span>{r.name}</span><small className="muted">{r.nights} nights</small></li>)}</ol>
            {perfect.length > 0 && <p className="small">⭐ <b>Perfect attendance:</b> {perfect.join(", ")}</p>}
          </div>
        )}
        {streaks.length > 0 && (
          <div className="award-card">
            <h4>Streaks</h4>
            <ol>{streaks.map((s) => <li key={s.name}><span>🔥 {s.name}</span><small className="muted">{s.nights} nights in a row</small></li>)}</ol>
          </div>
        )}
        {newcomers.length > 0 && (
          <div className="award-card">
            <h4>Newest voices</h4>
            <ul>{newcomers.map((n) => <li key={n.name}><span>🎉 {n.name}</span><small className="muted">first night: {n.event} · {day(n.date)}</small></li>)}</ul>
          </div>
        )}
      </div>
    </section>
  );
}
