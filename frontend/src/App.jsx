import { Link, Navigate, Route, Routes } from "react-router-dom";
import HostGate from "./pages/HostGate";
import EventPicker from "./pages/EventPicker";
import HostScreen from "./pages/HostScreen";
import HostRemote from "./pages/HostRemote";
import HostAdmin from "./pages/HostAdmin";
import JoinApp from "./pages/JoinApp";

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
      <Route path="/host" element={<HostGate><EventPicker /></HostGate>} />
      <Route path="/host/admin" element={<HostGate><HostAdmin /></HostGate>} />
      <Route path="/host/event/:eventId" element={<HostGate><HostScreen /></HostGate>} />
      <Route path="/host/remote/:eventId" element={<HostGate><HostRemote /></HostGate>} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
