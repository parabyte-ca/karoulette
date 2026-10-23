import { useEffect, useRef, useState } from "react";
import { api } from "../lib/api";
import { SCHEMES, applyAppearance } from "../lib/schemes";

const STAGE_PREVIEW = "/banners/main-stage-800.jpg";

/** A miniature TV screen and phone, drawn with the tokens of the card's data-scheme. */
function SchemePreview({ id, banner }) {
  return (
    <div className="mock" aria-hidden="true">
      <div className="mock-tv">
        <div className={`mock-top ${banner ? "mock-marquee" : ""}`} style={banner ? { "--mock-banner": `url("${banner}")` } : undefined}>
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

/** The banner photo: Main Stage's built-in one, or the host's own upload, optionally on every skin. */
function BannerSettings({ appearance, onChange, push }) {
  const fileRef = useRef(null);
  const [busy, setBusy] = useState(false);
  const custom = appearance.custom_banner;
  const preview = appearance.custom_url || STAGE_PREVIEW;

  const upload = async (file) => {
    if (!file) return;
    setBusy(true);
    try {
      const res = await fetch("/api/host/appearance/banner", { method: "PUT", body: file, credentials: "same-origin",
        headers: { "Content-Type": file.type || "application/octet-stream" } });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(body.detail || `Upload failed (${res.status})`);
      onChange(body);
      push(body.banner ? "New banner is up. The TV and phones show it now." : "New banner saved. Pick Main Stage, or show it with every skin, to see it.", "success");
    } catch (e) { push(e.message, "error"); } finally { setBusy(false); if (fileRef.current) fileRef.current.value = ""; }
  };
  const remove = async () => {
    if (!window.confirm("Remove your banner? Main Stage goes back to its built-in band photo.")) return;
    setBusy(true);
    try { onChange(await api("/api/host/appearance/banner", { method: "DELETE" })); push("Banner removed.", "success"); }
    catch (e) { push(e.message, "error"); } finally { setBusy(false); }
  };
  const toggleAll = async (on) => {
    setBusy(true);
    try { onChange(await api("/api/host/appearance/banner-all", { method: "PUT", body: { on } })); }
    catch (e) { push(e.message, "error"); } finally { setBusy(false); }
  };

  return (
    <div className="banner-settings">
      <h3>Banner photo</h3>
      <p className="muted small">Shown across the top of the TV like a festival marquee, behind the TV's QR and smoke
        break screens, at the top of the end-of-night recap, on guests' phones and in the preview when you share a join
        link. Main Stage comes with a band photo; upload your own (a wide JPEG, PNG or WebP, up to 8 MB) to swap it.</p>
      <div className="banner-row">
        <img className="banner-preview" src={preview} alt="Current banner" />
        <div className="banner-actions">
          <p className="small"><strong>{custom ? "Your uploaded banner" : "Main Stage's built-in band photo"}</strong></p>
          <button className="btn btn-primary" disabled={busy} onClick={() => fileRef.current?.click()}>
            {custom ? "Upload a different banner" : "Upload a banner"}
          </button>
          <input ref={fileRef} type="file" accept="image/jpeg,image/png,image/webp" hidden disabled={busy}
                 data-testid="banner-file" onChange={(e) => upload(e.target.files[0])} />
          {custom && <button className="btn btn-danger" disabled={busy} onClick={remove}>Remove my banner</button>}
          <label className="check">
            <input type="checkbox" checked={appearance.banner_all} disabled={busy || !custom}
                   onChange={(e) => toggleAll(e.target.checked)} />
            <span>Show my banner with every skin{custom ? "" : " (upload one first)"}</span>
          </label>
        </div>
      </div>
    </div>
  );
}

export default function AppearanceTab({ push }) {
  const [appearance, setAppearance] = useState(null);
  const [saving, setSaving] = useState(null);
  const current = appearance?.scheme;

  useEffect(() => {
    api("/api/public/appearance").then(setAppearance).catch((e) => push(e.message, "error"));
  }, [push]);

  const changed = (a) => { setAppearance(a); applyAppearance(a); };

  const choose = async (id) => {
    setSaving(id);
    try {
      const a = await api("/api/host/appearance", { method: "PUT", body: { scheme: id } });
      changed(a);
      push(`${SCHEMES.find((s) => s.id === a.scheme).name} is on. The TV and phones switch now.`, "success");
    } catch (e) {
      push(e.message, "error");
    } finally {
      setSaving(null);
    }
  };

  // What each card's preview shows in its marquee: Main Stage's photo (or the upload), or the upload on every skin.
  const customUrl = appearance?.custom_url;
  const previewBanner = (id) => (id === "stage" ? customUrl || STAGE_PREVIEW : appearance?.banner_all ? customUrl : null);

  return (
    <section className="card">
      <h2>Appearance</h2>
      <p className="muted">Pick a colour scheme for the TV screen, the guests' phones and this admin page. It changes
        everywhere straight away, even mid-event. Every scheme stays dark and high-contrast so the TV is easy to read
        across a dim room.</p>
      <div className="scheme-grid">
        {SCHEMES.map((s) => (
          <article key={s.id} data-scheme={s.id} className={`scheme-card ${current === s.id ? "selected" : ""}`}>
            <SchemePreview id={s.id} banner={previewBanner(s.id)} />
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
      {appearance && <BannerSettings appearance={appearance} onChange={changed} push={push} />}
    </section>
  );
}
