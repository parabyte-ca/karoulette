import { useCallback, useState } from "react";

export function useToasts() {
  const [toasts, setToasts] = useState([]);
  const push = useCallback((text, level = "info", ms = 6000) => {
    const id = Math.random().toString(36).slice(2);
    setToasts((t) => [...t.slice(-3), { id, text, level }]);
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), ms);
  }, []);
  return { toasts, push };
}

export function Toasts({ toasts }) {
  return (
    <div className="toasts" role="status" aria-live="polite">
      {toasts.map((t) => (
        <div key={t.id} className={`toast toast-${t.level}`}>{t.text}</div>
      ))}
    </div>
  );
}
