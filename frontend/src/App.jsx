import { lazy, Suspense } from "react";
import { Link, Navigate, Route, Routes } from "react-router-dom";
import HostGate from "./pages/HostGate";
import JoinApp from "./pages/JoinApp";

// Guests' phones only need the landing and join pages; the host pages load when first opened.
const EventPicker = lazy(() => import("./pages/EventPicker"));
const HostScreen = lazy(() => import("./pages/HostScreen"));
const HostRemote = lazy(() => import("./pages/HostRemote"));
const HostAdmin = lazy(() => import("./pages/HostAdmin"));

const loading = <main className="center-page"><p className="muted">Loading…</p></main>;
const host = (page) => <HostGate><Suspense fallback={loading}>{page}</Suspense></HostGate>;

function Landing() {
  return (
    <main className="landing">
      <h1 className="brand">Kar<span>oulette</span></h1>
      <p className="muted">Grab the mic. Queue your songs. Sing your heart out.</p>
      <div className="landing-actions">
        <Link className="btn btn-primary btn-xl" to="/join">I'm a guest</Link>
        <Link className="btn btn-xl" to="/host">I'm the host</Link>
      </div>
    </main>
  );
}

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Landing />} />
      <Route path="/join" element={<JoinApp />} />
      <Route path="/join/:code" element={<JoinApp />} />
      <Route path="/host" element={host(<EventPicker />)} />
      <Route path="/host/admin" element={host(<HostAdmin />)} />
      <Route path="/host/event/:eventId" element={host(<HostScreen />)} />
      <Route path="/host/remote/:eventId" element={host(<HostRemote />)} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
