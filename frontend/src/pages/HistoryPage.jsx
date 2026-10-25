import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../lib/api";
import HistoryDashboard from "../components/History";

/** The read-only song history guests can open at /history (when the host shares it). */
export default function HistoryPage() {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  useEffect(() => {
    document.title = "Song history · Karoulette";
    api("/api/public/history").then(setData).catch((e) => setError(e.message));
  }, []);
  return (
    <main className="page">
      <header className="page-header">
        <h1 className="brand small">Kar<span>oulette</span> <span className="muted">song history</span></h1>
        <Link className="btn" to="/join">Join an event</Link>
      </header>
      {error ? <section className="card"><p>{error}</p></section>
        : !data ? <p className="muted">Loading the song history…</p>
          : <section className="card"><HistoryDashboard songs={data.songs} awards={data.awards} /></section>}
    </main>
  );
}
