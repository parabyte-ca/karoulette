import { decodeEntities } from "../lib/format";

const STATUS = {
  singing: ["🎤", "singing now"],
  sung: ["✓", "sung"],
  picked: ["♪", null],
  pending: ["⏳", "picking…"],
  passed: ["–", "sat out"],
  skipped: ["–", "skipped"],
};

/** The Superset line-up: every singer's turn in order, with their pick or where they're at. */
export function SupersetLineup({ superset, myId = null, onFlag = null }) {
  return (
    <ol className="set-lineup">
      {superset.slots.map((s) => {
        const [icon, label] = STATUS[s.status] || ["", s.status];
        const waiting = superset.waiting_for === s.guest_id;
        return (
          <li key={s.guest_id} className={`set-slot ${s.status} ${waiting ? "waiting" : ""} ${s.guest_id === myId ? "mine" : ""}`}>
            <span className="set-icon" aria-hidden="true">{icon}</span>
            <span className="set-name">{s.name}{s.duet_name ? ` & ${s.duet_name}` : ""}</span>
            <span className="set-what">
              {waiting ? "everyone's waiting for their pick!" : label || decodeEntities(s.title)}
            </span>
            {onFlag && s.item_id && s.guest_id !== myId && ["picked", "singing"].includes(s.status) && (
              <button className="btn flag-btn" title="Flag as off-theme" onClick={() => onFlag(s.item_id)}>⚑</button>
            )}
          </li>
        );
      })}
    </ol>
  );
}

/** "Start now (this song kicks it off)" or "After this song": asked of whoever calls a Superset. */
export function SupersetChooser({ nowPlaying, title = "Call a Superset", note, onChoose, onClose }) {
  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="card modal" onClick={(e) => e.stopPropagation()} role="dialog" aria-label={title}>
        <h2>★ {title}</h2>
        <p className="muted">Everyone picks one extra song that fits, and we go round in singer order. Then the queue
          carries on. {note}</p>
        <div className="chooser">
          {nowPlaying && (
            <button className="btn btn-gold btn-block" onClick={() => onChoose("now")}>
              Start now: “{decodeEntities(nowPlaying.title)}” kicks it off
              <small>The theme becomes songs like this one.</small>
            </button>
          )}
          <button className={`btn btn-block ${nowPlaying ? "" : "btn-gold"}`} onClick={() => onChoose("after")}>
            {nowPlaying ? "After this song" : "Start the Superset"}
            <small>A theme is spun for everyone.</small>
          </button>
          <button className="btn btn-link btn-block" onClick={onClose}>Never mind</button>
        </div>
      </div>
    </div>
  );
}
