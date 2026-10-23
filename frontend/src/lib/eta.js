// Wait estimates for the phone: how long until a queued song's "Get ready" countdown starts.
const UNKNOWN_DURATION_S = 240; // same guess the server's recap uses

const length = (item) => item?.duration_s || UNKNOWN_DURATION_S;

/** Seconds until queue[index] is called up, from now (epoch seconds, server clock). */
export function secondsUntil(state, index, now) {
  const ready = Number(state.event.config.ready_seconds) || 0;
  let total = 0;
  const playing = state.now_playing;
  if (playing) total += Math.max(0, (playing.starts_at || now) + length(playing) - now);
  // A Superset under way plays all its turns before the queue carries on.
  for (const slot of state.superset?.slots || []) {
    if (slot.status === "pending" || slot.status === "picked") total += ready + length(slot);
  }
  for (let i = 0; i < index; i += 1) total += ready + length(state.queue[i]);
  return total;
}

export function formatWait(seconds) {
  if (seconds < 45) return "any moment now";
  const min = Math.max(1, Math.round(seconds / 60));
  return min >= 60 ? `≈ ${Math.floor(min / 60)} h ${String(min % 60).padStart(2, "0")} min` : `≈ ${min} min`;
}

/** Display name for a song's singer(s): "Alex" or "Alex & Blake". */
export const singers = (item) => (item.duet_name ? `${item.guest_name} & ${item.duet_name}` : item.guest_name);

/** Is this guest on the song, as the singer who picked it or as the duet partner? */
export const sings = (item, guestId) => !!item && (item.guest_id === guestId || item.duet_guest_id === guestId);
