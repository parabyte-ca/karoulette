import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../lib/api";

export default function EventPicker() {
  const [events, setEvents] = useState(null);
  const [name, setName] = useState("");
  const [error, setError] = useState("");
  const navigate = useNavigate();

  const load = () => api("/api/host/events").then(setEvents).catch((e) => setError(e.message));
  useEffect(() => { load(); }, []);

  const create = async (e) => {
    e.preventDefault();
    setError("");
    try {
      const ev = await api("/api/host/events", { method: "POST", body: { name } });
      navigate(`/host/event/${ev.id}`);
    } catch (err) {
      setError(err.message);
    }
  };

  const open = (events || []).filter((e) => e.status !== "ended");
  const ended = (events || []).filter((e) => e.status === "ended");

  return (
    <main className="page">
      <header className="page-header">
        <h1 className="brand small">Kar<span>oulette</span></h1>
        <Link to="/host/admin" className="btn">Host admin</Link>
      </header>
      <section className="card">
        <h2>Start a new event</h2>
        <form className="row" onSubmit={create}>
          <input placeholder="Event name, e.g. Saturday Singalong" value={name} maxLength={80}
                 onChange={(e) => setName(e.target.value)} required />
          <button className="btn btn-primary" disabled={!name.trim()}>Create event</button>
        </form>
        {error && <p className="error">{error}</p>}
      </section>
      <section className="card">
        <h2>Open events</h2>
        {!events && <p className="muted">Loading…</p>}
        {events && !open.length && <p className="muted">No open events yet. Create one above.</p>}
        <ul className="list">
          {open.map((ev) => (
            <li key={ev.id} className="list-row">
              <div>
                <strong>{ev.name}</strong>
                <div className="muted small">
                  Code {ev.join_code} · {ev.status === "active" ? "Running" : "Not started"} ·
                  {" "}{ev.guest_count} singers · {ev.songs_played} songs sung
                </div>
              </div>
              <Link className="btn btn-primary" to={`/host/event/${ev.id}`}>Open TV screen</Link>
            </li>
          ))}
        </ul>
      </section>
      {ended.length > 0 && (
        <section className="card">
          <h2>Past events</h2>
          <ul className="list">
            {ended.map((ev) => (
              <li key={ev.id} className="list-row">
                <div>
                  <strong>{ev.name}</strong>
                  <div className="muted small">{ev.songs_played} songs sung · {ev.current_round} rounds</div>
                </div>
                <a className="btn" href={`/api/host/events/${ev.id}/history.csv`}>Export CSV</a>
              </li>
            ))}
          </ul>
        </section>
      )}
    </main>
  );
}
