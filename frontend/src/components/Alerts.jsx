import { useEffect, useState } from "react";
import { DEFAULT_PREFS, KINDS, disablePush, enablePush, iosNeedsInstall, pushSupported, savedPrefs, setPushPrefs,
  syncPush } from "../lib/push";

function KindChecks({ prefs, onChange, disabled }) {
  return (
    <ul className="alert-kinds">
      {KINDS.map(([k, label, hint]) => (
        <li key={k}>
          <label className="check">
            <input type="checkbox" checked={!!prefs[k]} disabled={disabled} onChange={() => onChange({ ...prefs, [k]: !prefs[k] })} />
            <span>{label}<br /><span className="muted small">{hint}</span></span>
          </label>
        </li>
      ))}
    </ul>
  );
}

/** Lock-screen alerts for a guest: turn on, pick which kinds, or turn off. */
export function useAlerts() {
  const [prefs, setPrefs] = useState(savedPrefs);
  useEffect(() => { syncPush().then(setPrefs); }, []); // tonight's guest takes over this phone's alerts
  return [prefs, setPrefs];
}

/** The "Turn on alerts" offer in the status card: pick kinds, then allow notifications. */
export function AlertsOffer({ onOn, push }) {
  const [open, setOpen] = useState(false);
  const [prefs, setPrefs] = useState(DEFAULT_PREFS);
  const [busy, setBusy] = useState(false);
  if (iosNeedsInstall()) {
    return open ? (
      <div className="alerts-offer">
        <p className="small"><strong>🔔 Alerts on iPhone</strong><br />Add Karoulette to your Home Screen first: tap Share,
          then “Add to Home Screen”. Open it from there and turn alerts on (iOS 16.4 or later).</p>
        <button className="btn btn-link small" onClick={() => setOpen(false)}>Got it</button>
      </div>
    ) : <button className="btn btn-link small" onClick={() => setOpen(true)}>🔔 Buzz me when I'm nearly up</button>;
  }
  if (!pushSupported()) return null;
  if (!open) return <button className="btn btn-link small" onClick={() => setOpen(true)}>🔔 Buzz me when I'm nearly up</button>;
  const turnOn = async () => {
    setBusy(true);
    try {
      const saved = await enablePush(prefs);
      onOn(saved);
      push("🔔 Alerts on. They reach your phone even when it's locked.", "success");
    } catch (e) { push(e.message, "warning", 9000); } finally { setBusy(false); }
  };
  return (
    <div className="alerts-offer">
      <p className="small"><strong>🔔 Alerts on your lock screen</strong><br />
        <span className="muted">Pick what you'd like. Your phone will ask to allow notifications.</span></p>
      <KindChecks prefs={prefs} onChange={setPrefs} disabled={busy} />
      <div className="row wrap">
        <button className="btn btn-primary" disabled={busy || !Object.values(prefs).some(Boolean)} onClick={turnOn}>Turn on alerts</button>
        <button className="btn btn-link" onClick={() => setOpen(false)}>Not now</button>
      </div>
    </div>
  );
}

/** Footer settings once alerts are on. */
export function AlertsSettings({ prefs, onChange, push }) {
  const [busy, setBusy] = useState(false);
  const save = async (next) => {
    const before = prefs;
    onChange(next); // tick straight away; put it back if the server says no
    setBusy(true);
    try { onChange(await setPushPrefs(next)); } catch (e) { onChange(before); push(e.message, "error"); } finally { setBusy(false); }
  };
  const off = async () => {
    setBusy(true);
    try { await disablePush(); onChange(null); push("Alerts off.", "info"); } finally { setBusy(false); }
  };
  return (
    <details className="alerts-settings small">
      <summary>🔔 Alerts are on</summary>
      <KindChecks prefs={prefs} onChange={save} disabled={busy} />
      <button className="btn btn-link small" disabled={busy} onClick={off}>Turn alerts off</button>
    </details>
  );
}
