import { useCountdown } from "../lib/useEventSocket";

export default function Countdown({ deadline, remaining, serverNow, total, paused }) {
  const left = useCountdown(paused ? null : deadline, serverNow, remaining);
  if (left == null) return null;
  const secs = Math.ceil(left);
  const pct = total ? Math.max(0, Math.min(100, (left / total) * 100)) : null;
  return (
    <div className={`countdown ${secs <= 10 ? "urgent" : ""}`}>
      <span className="countdown-num">{paused ? "⏸" : secs}</span>
      {pct != null && (
        <div className="countdown-bar"><div style={{ width: `${pct}%` }} /></div>
      )}
    </div>
  );
}
