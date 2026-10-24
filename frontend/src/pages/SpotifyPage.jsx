import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { finishSpotify } from "../lib/playlists";

/** /spotify — where Spotify sends people back after signing in: makes the playlist, then links to it. */
export default function SpotifyPage() {
  const [progress, setProgress] = useState(null);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const started = useRef(false);
  useEffect(() => {
    if (started.current) return; // the sign-in code works once (and React runs effects twice in dev)
    started.current = true;
    finishSpotify(window.location.search, (done, total) => setProgress({ done, total }))
      .then(setResult).catch(setError);
  }, []);
  const back = result?.returnTo || error?.returnTo || "/";
  return (
    <main className="page narrow-page">
      <header className="page-header"><h1 className="brand small">Kar<span>oulette</span></h1></header>
      <section className="card">
        <h2>Spotify playlist</h2>
        {error ? <p className="error">{error.message}</p> : result ? (
          <>
            <p>“{result.name}” is in your Spotify with {result.added} song{result.added === 1 ? "" : "s"}.</p>
            <a className="btn btn-spotify" href={result.url} target="_blank" rel="noreferrer">Open in Spotify ↗</a>
            {result.missed.length > 0 && (
              <details className="small"><summary>{result.missed.length} not found on Spotify</summary>
                <ul>{result.missed.map((m) => <li key={m}>{m}</li>)}</ul></details>
            )}
          </>
        ) : (
          <div className="playlist-progress" role="status">
            <span>{progress ? `Finding the songs on Spotify… ${progress.done}/${progress.total}` : "Signing in to Spotify…"}</span>
            {progress && <span className="bar-track"><span className="bar" style={{ width: `${(progress.done / progress.total) * 100}%` }} /></span>}
          </div>
        )}
        <p><Link to={back}>← Back</Link></p>
      </section>
    </main>
  );
}
