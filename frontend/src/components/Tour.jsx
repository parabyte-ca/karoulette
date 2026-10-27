import { useEffect, useLayoutEffect, useRef, useState } from "react";

const GAP = 12; // between the highlighted element and the tip
const PAD = 8; // around the highlighted element

/**
 * A step-by-step spotlight tour. Each step highlights the element matching `target` (a CSS selector) and shows a
 * tip beside it; a step without a target, or whose target isn't on screen, shows the tip in the centre. Steps marked
 * `optional` are left out when their target is missing (a duet picker before anyone else has joined, say).
 */
export default function Tour({ steps, onClose, label = "Guided tour" }) {
  const [list, setList] = useState([]);
  // Optional steps are checked once the page has rendered, so a target drawn in the same pass counts.
  useLayoutEffect(() => {
    setList(steps.filter((s) => !s.optional || document.querySelector(s.target)));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  const [n, setN] = useState(0);
  const [rect, setRect] = useState(null);
  const [tipSize, setTipSize] = useState({ w: 340, h: 200 });
  const tipRef = useRef(null);
  const nextRef = useRef(null);
  const step = list[n];
  const last = n === list.length - 1;

  // Find the step's element, bring it into view, then follow it as the live page moves around.
  useEffect(() => {
    if (!step) return undefined;
    const find = () => (step.target ? document.querySelector(step.target) : null);
    const el = find();
    el?.scrollIntoView({ block: "center", behavior: "smooth" });
    const measure = () => {
      const r = find()?.getBoundingClientRect();
      setRect(r && r.width ? { top: r.top, left: r.left, width: r.width, height: r.height } : null);
    };
    measure();
    const timer = setInterval(measure, 200);
    window.addEventListener("resize", measure);
    return () => { clearInterval(timer); window.removeEventListener("resize", measure); };
  }, [step]);

  useLayoutEffect(() => {
    const r = tipRef.current?.getBoundingClientRect();
    if (r && (Math.abs(r.width - tipSize.w) > 1 || Math.abs(r.height - tipSize.h) > 1)) setTipSize({ w: r.width, h: r.height });
  });
  useEffect(() => { nextRef.current?.focus({ preventScroll: true }); }, [n]);

  const finish = (completed) => onClose?.(completed);
  // Keys belong to the tour while it's open, so the TV's shortcuts (space, N, S…) don't fire underneath.
  useEffect(() => {
    const onKey = (e) => {
      e.stopPropagation();
      if (e.key === "Escape") finish(false);
      else if (e.key === "ArrowRight") { if (last) finish(true); else setN((i) => i + 1); }
      else if (e.key === "ArrowLeft") setN((i) => Math.max(0, i - 1));
    };
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  });

  if (!step) return null;

  const vw = window.innerWidth;
  const vh = window.innerHeight;
  let tipStyle;
  if (rect) {
    const below = rect.top + rect.height + PAD + GAP;
    const above = rect.top - PAD - GAP - tipSize.h;
    // Below if it fits, else above; failing both, pin it to the roomier edge of the screen.
    const roomier = vh - (rect.top + rect.height) > rect.top ? vh - tipSize.h - 16 : 16;
    const top = below + tipSize.h <= vh - 16 ? below : above >= 16 ? above : Math.max(16, roomier);
    const left = Math.max(16, Math.min(vw - tipSize.w - 16, rect.left + rect.width / 2 - tipSize.w / 2));
    tipStyle = { top, left };
  }

  return (
    <div className="tour" role="dialog" aria-modal="true" aria-label={label} aria-describedby="tour-body">
      {rect ? (
        <div className="tour-hole" style={{ top: rect.top - PAD, left: rect.left - PAD,
          width: rect.width + PAD * 2, height: rect.height + PAD * 2 }} />
      ) : <div className="tour-shade" />}
      <div className={`card tour-tip ${rect ? "" : "centred"}`} style={tipStyle} ref={tipRef}>
        <div className="tour-head">
          <span className="label">{n + 1} of {list.length}</span>
          <button className="btn btn-link small" onClick={() => finish(false)}>Skip tour</button>
        </div>
        <h3>{step.title}</h3>
        <div id="tour-body" className="tour-body">{step.body}</div>
        <div className="tour-dots" aria-hidden="true">
          {list.map((s, i) => <span key={s.title} className={i === n ? "on" : ""} />)}
        </div>
        <div className="tour-actions">
          {n > 0 && <button className="btn" onClick={() => setN(n - 1)}>Back</button>}
          <button ref={nextRef} className="btn btn-primary" onClick={() => (last ? finish(true) : setN(n + 1))}>
            {last ? step.done || "Got it" : "Next"}
          </button>
        </div>
      </div>
    </div>
  );
}
