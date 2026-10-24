import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../lib/api";
import { decodeEntities } from "../lib/format";
import PlaylistButtons from "../components/PlaylistButtons";

const day = (t) => new Date(t * 1000).toLocaleDateString("en-CA", { year: "numeric", month: "long", day: "numeric" });

/** /playlist/:code — an event's songs as a YouTube or Spotify playlist (the TV recap's QR code opens this). */
export default function PlaylistPage() {
  const { code } = useParams();
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  useEffect(() => {
    api(`/api/public/events/${encodeURIComponent(code)}/playlist`)
      .then((d) => { setData(d); document.title = `${d.event.name}: the playlist · Karoulette`; })
      .catch((e) => setError(e.message));
  }, [code]);

  if (error) return <main className="page"><section className="card"><p>{error}</p><Link to="/">Home</Link></section></main>;
  if (!data) return <main className="page"><p className="muted">Loading the playlist…</p></main>;
  const { event, tracks } = data;
  return (
    <main className="page narrow-page">
      <header className="page-header">
        <h1 className="brand small">Kar<span>oulette</span></h1>
        {event.status !== "ended" && <Link className="btn" to={`/join/${event.code}`}>Join the party</Link>}
      </header>
      <section className="card">
        <div className="label">The playlist</div>
        <h2>{event.name}</h2>
        <p className="muted">{day(event.date)} · {tracks.length} song{tracks.length === 1 ? "" : "s"}
          {event.status !== "ended" && " so far"}</p>
        {tracks.length ? (
          <PlaylistButtons code={event.code} name={`${event.name} · Karoulette`}
                           description={`The songs from ${event.name} (${day(event.date)}), made with Karoulette 🎤`}
                           items={tracks.map((t) => ({ item_id: t.item_id, track: t.track }))} />
        ) : <p className="muted">No songs have played yet.</p>}
        <ol className="playlist-tracks">
          {tracks.map((t) => (
            <li key={t.item_id}>
              <b>{decodeEntities(t.track)}</b>
              <span className="muted small">sung by {t.singer}{t.duet ? ` & ${t.duet}` : ""}</span>
            </li>
          ))}
        </ol>
      </section>
    </main>
  );
}
