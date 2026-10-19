import { useEffect, useRef, useState } from "react";

/**
 * Slot-machine style spin. Cycles through candidate names, slowing down, and lands on
 * `result` after `duration` seconds. Re-runs whenever `spinKey` changes.
 */
export default function ThemeSpinner({ spinKey, candidates, result, duration = 5, superset = false, size = "lg" }) {
  const [label, setLabel] = useState(result || "");
  const [landed, setLanded] = useState(false);
  const timers = useRef([]);

  useEffect(() => {
    timers.current.forEach(clearTimeout);
    timers.current = [];
    const names = (candidates && candidates.length ? candidates : [result]).filter(Boolean);
    if (!result || names.length < 2) {
      setLabel(result || "");
      setLanded(true);
      return undefined;
    }
    setLanded(false);
    const total = Math.max(1000, duration * 1000 - 600);
    let t = 0;
    let i = Math.floor(Math.random() * names.length);
    let step = 60;
    while (t < total) {
      const name = names[i % names.length];
      timers.current.push(setTimeout(() => setLabel(name), t));
      t += step;
      step = Math.min(step * 1.12, 450);
      i += 1;
    }
    timers.current.push(setTimeout(() => { setLabel(result); setLanded(true); }, t));
    return () => timers.current.forEach(clearTimeout);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [spinKey, result]);

  return (
    <div className={`spinner spinner-${size} ${landed ? "landed" : "spinning"} ${superset ? "superset" : ""}`}>
      <div className="spinner-window">
        <span key={label} className="spinner-label">{label}</span>
      </div>
    </div>
  );
}
