import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../lib/api";
import Tour from "../components/Tour";
import { markTourSeen, shouldShowTour } from "../lib/tour";

const START_TOUR = [
  { title: "👋 Welcome, host!", body: "A few quick things, then you're ready for your first night." },
  { target: '[data-tour="create"]', title: "Start here",
    body: "Name your event and tap Create event on the browser that's connected to the TV. It opens the TV screen, which has its own short tour." },
  { target: '[data-tour="events"]', title: "Your events",
    body: "Open the TV screen for an event, or 📱 Remote to run it from your phone. Guests can join and add songs before you start." },
  { target: '[data-tour="admin"]', title: "Host admin",
    body: "Event rules, singer order, themes, colours, song history, backups, updates and your PIN." },
  { target: '[data-tour="help"]', title: "Help for hosts and singers", done: "Got it",
    body: "Answers to common questions, and this tour again whenever you want it." },
];

export default function EventPicker() {
  const [events, setEvents] = useState(null);
  const [name, setName] = useState("");
  const [error, setError] = useState("");
  const [touring, setTouring] = useState(() => shouldShowTour("host-start"));
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

  const open = (events || []).filter((e) => e.status !== "ended" && !e.archived_at);
  const ended = (events || []).filter((e) => e.status === "ended" && !e.archived_at);

  return (
    <main className="page">
      <header className="page-header">
        <h1 className="brand small">Kar<span>oulette</span></h1>
        <span className="actions">
          <Link to="/help?for=host" className="btn" data-tour="help">❓ Help</Link>
          <Link to="/host/admin" className="btn" data-tour="admin">Host admin</Link>
        </span>
      </header>
      <section className="card" data-tour="create">
        <h2>Start a new event</h2>
        <form className="row" onSubmit={create}>
          <input placeholder="Event name, e.g. Saturday Singalong" value={name} maxLength={80}
                 onChange={(e) => setName(e.target.value)} required />
          <button className="btn btn-primary" disabled={!name.trim()}>Create event</button>
        </form>
        {error && <p className="error">{error}</p>}
      </section>
      <section className="card" data-tour="events">
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
              <span className="actions">
                <Link className="btn" to={`/host/remote/${ev.id}`} title="Control the event from this phone">📱 Remote</Link>
                <Link className="btn btn-primary" to={`/host/event/${ev.id}`}>Open TV screen</Link>
              </span>
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
      {touring && events && (
        <Tour steps={START_TOUR} label="Host tour" onClose={() => { markTourSeen("host-start"); setTouring(false); }} />
      )}
    </main>
  );
}
