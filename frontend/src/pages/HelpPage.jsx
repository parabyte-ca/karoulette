import { Fragment, useEffect, useMemo, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { guestSession } from "../lib/api";
import { HOST_HELP, SINGER_HELP, entryText } from "../lib/help";
import { resetTours } from "../lib/tour";

/** **bold** and `code` inside one paragraph. */
function Inline({ text }) {
  return text.split(/(\*\*[^*]+\*\*|`[^`]+`)/).map((part, i) => {
    if (part.startsWith("**")) return <strong key={i}>{part.slice(2, -2)}</strong>;
    if (part.startsWith("`")) return <code key={i}>{part.slice(1, -1)}</code>;
    return <Fragment key={i}>{part}</Fragment>;
  });
}

/** Paragraphs, with runs of "1. " or "- " lines turned into lists. */
function Answer({ lines }) {
  const blocks = [];
  for (const line of lines) {
    const kind = /^\d+\. /.test(line) ? "ol" : line.startsWith("- ") ? "ul" : "p";
    const text = kind === "p" ? line : line.replace(/^(\d+\. |- )/, "");
    const prev = blocks[blocks.length - 1];
    if (kind !== "p" && prev?.kind === kind) prev.items.push(text);
    else blocks.push({ kind, items: [text] });
  }
  return blocks.map((b, i) => {
    if (b.kind === "p") return <p key={i}><Inline text={b.items[0]} /></p>;
    const List = b.kind;
    return <List key={i}>{b.items.map((t, j) => <li key={j}><Inline text={t} /></li>)}</List>;
  });
}

const QUICK = {
  singer: ["Scan the QR code on the TV", "Pick a name and add songs", "Sing when your phone says you're up"],
  host: ["Create an event on the TV's browser", "Guests scan the QR code", "Press Start and enjoy"],
};

export default function HelpPage() {
  const { search, hash } = useLocation();
  const navigate = useNavigate();
  const [who, setWho] = useState(() => (new URLSearchParams(search).get("for") === "host" ? "host" : "singer"));
  const [q, setQ] = useState("");
  const [note, setNote] = useState("");
  const sections = who === "host" ? HOST_HELP : SINGER_HELP;
  const anchor = hash.replace(/^#/, "");

  // A link straight to one question (/help#switch) opens it on the right tab.
  useEffect(() => {
    if (!anchor) return;
    if (HOST_HELP.some((s) => s.items.some((i) => i.id === anchor))) setWho("host");
    else if (SINGER_HELP.some((s) => s.items.some((i) => i.id === anchor))) setWho("singer");
    setTimeout(() => document.getElementById(anchor)?.scrollIntoView({ block: "start" }), 50);
  }, [anchor]);

  const shown = useMemo(() => {
    const words = q.toLowerCase().split(/\s+/).filter(Boolean);
    if (!words.length) return sections;
    return sections
      .map((s) => ({ ...s, items: s.items.filter((i) => words.every((w) => entryText(i).includes(w))) }))
      .filter((s) => s.items.length);
  }, [q, sections]);

  const switchTo = (w) => {
    setWho(w);
    setNote("");
    navigate({ search: w === "host" ? "?for=host" : "", hash: "" }, { replace: true });
  };

  const replay = () => {
    if (who === "host") {
      resetTours("host-start", "host-tv");
      navigate("/host");
    } else {
      resetTours("singer");
      if (guestSession.token && guestSession.code) navigate(`/join/${guestSession.code}`);
      else setNote("Done: the tour starts when you next join an event.");
    }
  };

  return (
    <main className="page help-page">
      <header className="page-header">
        <Link to="/" className="brand small">Kar<span>oulette</span> <span className="muted">help</span></Link>
        <button className="btn" onClick={() => (window.history.length > 1 ? navigate(-1) : navigate("/"))}>Back</button>
      </header>

      <nav className="tabs" aria-label="Help for">
        <button className={`tab ${who === "singer" ? "active" : ""}`} onClick={() => switchTo("singer")}>🎤 Singers</button>
        <button className={`tab ${who === "host" ? "active" : ""}`} onClick={() => switchTo("host")}>📺 Hosts</button>
      </nav>

      <section className="card help-intro">
        <h1>{who === "host" ? "Hosting a night" : "Singing tonight"}</h1>
        <ol className="help-quick">
          {QUICK[who].map((step) => <li key={step}>{step}</li>)}
        </ol>
        <div className="row wrap">
          <button className="btn btn-primary" onClick={replay}>🧭 {who === "host" ? "Take the host tour" : "Take the singer tour"}</button>
          {who === "singer" && guestSession.token && guestSession.code && (
            <Link className="btn" to={`/join/${guestSession.code}`}>Back to my event</Link>
          )}
        </div>
        {note && <p className="muted small">{note}</p>}
      </section>

      <input type="search" className="help-search" value={q} onChange={(e) => setQ(e.target.value)} maxLength={60}
             placeholder="Search the questions, e.g. duet, alerts, PIN" aria-label="Search help" />

      {!shown.length && (
        <p className="muted">Nothing matches “{q}”. {who === "singer" ? "Try other words, or ask the host." : "Try other words, or check the README."}
          {" "}<button className="btn btn-link" onClick={() => switchTo(who === "host" ? "singer" : "host")}>
            Look in {who === "host" ? "Singers" : "Hosts"}</button></p>
      )}

      {shown.map((s) => (
        <section key={s.title} className="card help-section">
          <h2>{s.title}</h2>
          {s.items.map((item) => (
            <details key={item.id} id={item.id} className="faq" open={!!q || anchor === item.id}>
              <summary>{item.q}</summary>
              <div className="faq-a"><Answer lines={item.a} /></div>
            </details>
          ))}
        </section>
      ))}
      <p className="muted small help-foot">{who === "singer" ? "Still stuck? The host can help." : "More detail is in the README on GitHub."}</p>
    </main>
  );
}
