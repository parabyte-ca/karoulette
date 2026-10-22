import { useEffect, useState } from "react";
import { api } from "../lib/api";
import { SCHEMES, applyScheme } from "../lib/schemes";

/** A miniature TV screen and phone, drawn with the tokens of the card's data-scheme. */
function SchemePreview({ id }) {
  return (
    <div className="mock" aria-hidden="true">
      <div className="mock-tv">
        <div className="mock-top">
          <span className="mock-brand">Kar<span>oulette</span></span>
          <span className="mock-round">Round 3</span>
          {id === "synthwave" || id === "aurora" ? <span className="mock-superset">★ SUPERSET · Power Ballads</span> : null}
        </div>
        <div className="mock-main">
          <div className="mock-stage">
            <div className="mock-lyrics">
              <span>Is this the real life?</span>
              <span className="sung">Is this just fantasy?</span>
            </div>
            <div className="mock-now"><b>Alex</b> Bohemian Rhapsody</div>
          </div>
          <div className="mock-side">
            <div className="mock-turn">
              <i>Round 3 theme</i>
              <b>80s</b>
              <span className="mock-pill">80s</span>
              <div className="mock-bar"><div /></div>
            </div>
            <div className="mock-queue">
              <i>Up next · Queue</i>
              <div className="mock-row next"><span /> <b>Casey</b></div>
              <div className="mock-row"><span /> <b>Devon</b></div>
            </div>
            <div className="mock-join"><span className="mock-qr" /><b>ABCDE</b></div>
          </div>
        </div>
      </div>
      <div className="mock-phone">
        <div className="mock-phone-card">
          <b>Up next!</b>
          <span className="mock-pill">80s</span>
          <div className="mock-input" />
          <div className="mock-btn">Search</div>
        </div>
      </div>
    </div>
  );
}

export default function AppearanceTab({ push }) {
  const [current, setCurrent] = useState(null);
  const [saving, setSaving] = useState(null);

  useEffect(() => {
    api("/api/public/appearance").then((a) => setCurrent(a.scheme)).catch((e) => push(e.message, "error"));
  }, [push]);

  const choose = async (id) => {
    setSaving(id);
    try {
      const a = await api("/api/host/appearance", { method: "PUT", body: { scheme: id } });
      setCurrent(a.scheme);
      applyScheme(a.scheme);
      push(`${SCHEMES.find((s) => s.id === a.scheme).name} is on. The TV and phones switch now.`, "success");
    } catch (e) {
      push(e.message, "error");
    } finally {
      setSaving(null);
    }
  };

  return (
    <section className="card">
      <h2>Appearance</h2>
      <p className="muted">Pick a colour scheme for the TV screen, the guests' phones and this admin page. It changes
        everywhere straight away, even mid-event. Every scheme stays dark and high-contrast so the TV is easy to read
        across a dim room.</p>
      <div className="scheme-grid">
        {SCHEMES.map((s) => (
          <article key={s.id} data-scheme={s.id} className={`scheme-card ${current === s.id ? "selected" : ""}`}>
            <SchemePreview id={s.id} />
            <div className="scheme-info">
              <h3>
                {s.name}
                {current === s.id && <span className="pill">In use</span>}
              </h3>
              <div className="swatches">
                {s.swatches.map((c) => <span key={c} style={{ background: c }} title={c} />)}
              </div>
              <p className="muted small">{s.tagline}</p>
              <button className={`btn ${current === s.id ? "" : "btn-primary"}`} disabled={current === s.id || !!saving}
                      onClick={() => choose(s.id)}>
                {current === s.id ? "Current scheme" : saving === s.id ? "Applying…" : "Use this scheme"}
              </button>
            </div>
          </article>
        ))}
      </div>
    </section>
  );
}
