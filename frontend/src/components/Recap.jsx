import { decodeEntities } from "../lib/format";
import { useBanner } from "../lib/schemes";

/** End-of-night summary: big stat tiles plus the night's highlights. `me` adds a personal line on phones. */
export default function Recap({ recap, eventName, me = null, size = "tv" }) {
  const { banner } = useBanner();
  if (!recap) return null;
  const tiles = [
    [recap.songs, recap.songs === 1 ? "song sung" : "songs sung"],
    [recap.singers, recap.singers === 1 ? "singer" : "singers"],
    [recap.minutes, "minutes of music"],
    [recap.rounds, recap.rounds === 1 ? "round" : "rounds"],
  ];
  if (recap.duets) tiles.push([recap.duets, recap.duets === 1 ? "duet" : "duets"]);
  if (recap.superset_rounds) tiles.push([recap.superset_rounds, recap.superset_rounds === 1 ? "Superset" : "Supersets"]);
  const mine = me ? recap.per_singer?.[me] || 0 : null;
  const highlights = [
    recap.crowd_favourite && ["🔥 Crowd favourite", `${recap.crowd_favourite.singer} · ${decodeEntities(recap.crowd_favourite.title)} (${recap.crowd_favourite.cheers} cheers)`],
    recap.most_loved && ["❤️ Most loved", `${recap.most_loved.singer} · ${decodeEntities(recap.most_loved.title)} (${recap.most_loved.likes} like${recap.most_loved.likes === 1 ? "" : "s"})`],
    recap.most_cheered && ["📣 Most cheered singer", `${recap.most_cheered.singer} (${recap.most_cheered.cheers} cheers)`],
    recap.top_singers.length > 0 && ["🏆 Most songs", `${recap.top_singers.join(", ")} (${recap.top_count})`],
    recap.top_themes.length > 0 && ["🎰 Top themes", recap.top_themes.join(", ")],
    recap.superset_stars.length > 0 && ["★ Superset stars", recap.superset_stars.join(", ")],
    recap.first_song && ["🎬 Opened the night", `${recap.first_song.singer} · ${decodeEntities(recap.first_song.title)}`],
    recap.last_song && recap.songs > 1 && ["🌙 Closed it out", `${recap.last_song.singer} · ${decodeEntities(recap.last_song.title)}`],
    recap.longest_song && ["⏱ Longest song", `${recap.longest_song.singer} · ${decodeEntities(recap.longest_song.title)}`],
    recap.awards?.first_nights.length > 0 && ["🎉 First night!", recap.awards.first_nights.join(", ")],
    recap.awards?.milestones.length > 0 && ["🏅 Milestones", recap.awards.milestones.join(" · ")],
    recap.late_joiners > 0 && ["🎉 Joined mid-party", `${recap.late_joiners} new singer${recap.late_joiners === 1 ? "" : "s"}`],
  ].filter(Boolean);

  return (
    <div className={`recap recap-${size}`}>
      <div className={banner ? "recap-banner" : undefined}>
        <div className="label">That's a wrap</div>
        <h2 className="recap-title">{eventName}</h2>
      </div>
      {mine !== null && (
        <p className="recap-me">{mine ? `You sang ${mine} song${mine === 1 ? "" : "s"} tonight. Bravo! 🎤` : "Thanks for cheering everyone on! 👏"}</p>
      )}
      <div className="recap-tiles">
        {tiles.map(([n, label]) => (
          <div key={label} className="recap-tile"><b>{n}</b><span>{label}</span></div>
        ))}
      </div>
      {highlights.length > 0 && (
        <dl className="recap-highlights">
          {highlights.map(([k, v]) => (
            <div key={k}><dt>{k}</dt><dd>{v}</dd></div>
          ))}
        </dl>
      )}
    </div>
  );
}
