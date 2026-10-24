import { useEffect, useState } from "react";
import { api } from "../lib/api";
import { findOriginals, playlistConfig, spotifyUsable, startSpotify, youtubeLinks } from "../lib/playlists";

/**
 * "YouTube playlist" and "Spotify playlist" buttons for a list of sung songs.
 * items: [{item_id, track}]; code: the event's join code (scopes the lookup to that event).
 */
export default function PlaylistButtons({ items, name, description, code = null, compact = false }) {
  const [spotifyId, setSpotifyId] = useState("");
  const [busy, setBusy] = useState(null); // {what, done, total}
  const [links, setLinks] = useState(null);
  const [note, setNote] = useState("");
  const [error, setError] = useState("");

  useEffect(() => { playlistConfig().then((c) => setSpotifyId(c.spotify_client_id || "")); }, []);
  useEffect(() => { setLinks(null); setNote(""); }, [items.length, name]);

  const youtube = async () => {
    setError("");
    setBusy({ what: "Finding the original songs", done: 0, total: items.length });
    try {
      const found = await findOriginals(items.map((i) => i.item_id), code,
        (done, total) => setBusy({ what: "Finding the original songs", done, total }));
      const ids = [...new Set(found.map((f) => f.video_id))];
      const missing = found.filter((f) => !f.original).length;
      setLinks(youtubeLinks(ids));
      setNote(missing ? `${found.length - missing} of ${found.length} originals found; the rest use the karaoke video.`
        : `${found.length} original song${found.length === 1 ? "" : "s"}.`);
    } catch (e) { setError(e.message); } finally { setBusy(null); }
  };

  const spotify = () => startSpotify(spotifyId, {
    name, description: description || "Made with Karoulette 🎤", tracks: items.map((i) => i.track),
    returnTo: window.location.pathname + window.location.search,
  }).catch((e) => setError(e.message));

  if (!items.length) return null;
  return (
    <div className={`playlist-buttons ${compact ? "compact" : ""}`}>
      <div className="row wrap">
        <button type="button" className="btn btn-primary" disabled={!!busy} onClick={youtube}>
          ▶ YouTube playlist ({items.length})
        </button>
        {spotifyId && spotifyUsable() && (
          <button type="button" className="btn btn-spotify" disabled={!!busy} onClick={spotify}>Spotify playlist</button>
        )}
      </div>
      {busy && (
        <div className="playlist-progress" role="status">
          <span>{busy.what}… {busy.done}/{busy.total}</span>
          <span className="bar-track"><span className="bar" style={{ width: `${(busy.done / busy.total) * 100}%` }} /></span>
        </div>
      )}
      {links && (
        <div className="playlist-links">
          {links.map((url, i) => (
            <a key={url} className="btn" href={url} target="_blank" rel="noreferrer">
              Open on YouTube{links.length > 1 ? ` (part ${i + 1} of ${links.length})` : ""} ↗</a>
          ))}
          <p className="muted small">{note}</p>
        </div>
      )}
      {error && <p className="error small">{error}</p>}
    </div>
  );
}

/** Playlist buttons for one event, loading its songs (phone recap). */
export function EventPlaylistButtons({ code, name, compact }) {
  const [items, setItems] = useState([]);
  useEffect(() => {
    api(`/api/public/events/${encodeURIComponent(code)}/playlist`)
      .then((d) => setItems(d.tracks.map((t) => ({ item_id: t.item_id, track: t.track })))).catch(() => {});
  }, [code]);
  return <PlaylistButtons code={code} name={`${name} · Karoulette`} items={items} compact={compact} />;
}
