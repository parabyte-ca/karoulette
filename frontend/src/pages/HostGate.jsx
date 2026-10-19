import { useEffect, useState } from "react";
import { api } from "../lib/api";

export default function HostGate({ children }) {
  const [status, setStatus] = useState("loading");
  const [pin, setPin] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api("/api/host/session")
      .then((s) => setStatus(s.authenticated ? "ok" : "login"))
      .catch((e) => { setError(e.message); setStatus("login"); });
  }, []);

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      await api("/api/host/login", { method: "POST", body: { pin } });
      setStatus("ok");
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  if (status === "loading") return <main className="center-page"><p className="muted">Loading…</p></main>;
  if (status === "ok") return children;
  return (
    <main className="center-page">
      <form className="card narrow" onSubmit={submit}>
        <h1 className="brand small">Karaoke<span>Queue</span></h1>
        <h2>Host sign-in</h2>
        <label className="field">
          <span>Host PIN or password</span>
          <input type="password" inputMode="text" autoComplete="current-password" autoFocus
                 value={pin} onChange={(e) => setPin(e.target.value)} maxLength={64} required />
        </label>
        {error && <p className="error">{error}</p>}
        <button className="btn btn-primary btn-block" disabled={busy || !pin}>Sign in</button>
        <p className="muted small">The PIN is set during setup (HOST_PIN in your .env file).</p>
      </form>
    </main>
  );
}
