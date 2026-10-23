import { useSyncExternalStore } from "react";

// Colour schemes. The tokens live in schemes.css; this is the list the admin page offers and the
// helper that applies the chosen one to <html data-scheme="...">.
export const SCHEMES = [
  {
    id: "neon",
    name: "Neon Night",
    tagline: "The original. Hot pink and electric cyan on midnight indigo, like a karaoke bar's neon sign.",
    swatches: ["#0b0b14", "#ff3d81", "#3dd6ff", "#ffd23f"],
  },
  {
    id: "onair",
    name: "On Air",
    tagline: "A broadcast studio: charcoal walls, a red ON AIR lamp, warm key light and monitor scanlines. Sits beside the YouTube player like it belongs there.",
    swatches: ["#0e0e0f", "#ff2e3b", "#ffb547", "#ffe08a"],
  },
  {
    id: "synthwave",
    name: "Synthwave Sunset",
    tagline: "An 80s outrun poster: a striped sun sinking behind a neon grid, magenta and teal lasers, chrome lettering.",
    swatches: ["#12002b", "#ff3fd1", "#2de2e6", "#ffb03b"],
  },
  {
    id: "velvet",
    name: "Velvet Lounge",
    tagline: "A late-night jazz club: burgundy velvet curtains, one warm spotlight, champagne gold and serif type.",
    swatches: ["#170609", "#e8445e", "#e9c98b", "#f2cf7d"],
  },
  {
    id: "aurora",
    name: "Northern Lights",
    tagline: "A Canadian winter sky: drifting green and violet aurora over a starry navy night. A nod to Canadiana.",
    swatches: ["#050d1c", "#36f1a6", "#9d8cff", "#ffe57a"],
  },
  {
    id: "disco",
    name: "Mirror Ball",
    tagline: "A 70s disco: a spinning mirror ball scatters rays and flecks of hot pink, ice blue and gold across a dark dance floor.",
    swatches: ["#0c0614", "#ff4fa3", "#7fe7ff", "#ffcc33"],
  },
  {
    id: "stage",
    name: "Main Stage",
    tagline: "A summer festival headliner: the band photo across the top like a marquee, smoke-red and stage-blue lights, amber spots and bold concert-poster lettering.",
    swatches: ["#070a1a", "#ff3b3b", "#4da3ff", "#ffb547"],
  },
];

const KEY = "kq_scheme";
const BANNER_KEY = "kq_banner";
const ids = new Set(SCHEMES.map((s) => s.id));

export function applyScheme(id) {
  const scheme = ids.has(id) ? id : "neon";
  const root = document.documentElement;
  if (root.dataset.scheme === scheme) return;
  root.dataset.scheme = scheme;
  try { localStorage.setItem(KEY, scheme); } catch { /* private mode */ }
  const meta = document.querySelector('meta[name="theme-color"]');
  if (meta) meta.setAttribute("content", SCHEMES.find((s) => s.id === scheme).swatches[0]);
}

// The banner photo (Main Stage's built-in one, or the host's upload). Pages read it with useBanner();
// the CSS reads --banner and --banner-small for the TV marquee and idle backdrops.
let banner = { banner: null, banner_small: null };
const listeners = new Set();

function setBanner(next) {
  const b = { banner: next?.banner || null, banner_small: next?.banner_small || next?.banner || null };
  if (b.banner === banner.banner && b.banner_small === banner.banner_small) return;
  banner = b;
  const root = document.documentElement;
  if (b.banner) {
    root.dataset.banner = "";
    root.style.setProperty("--banner", `url("${b.banner}")`);
    root.style.setProperty("--banner-small", `url("${b.banner_small}")`);
  } else {
    delete root.dataset.banner;
    root.style.removeProperty("--banner");
    root.style.removeProperty("--banner-small");
  }
  try { localStorage.setItem(BANNER_KEY, JSON.stringify(b)); } catch { /* private mode */ }
  listeners.forEach((fn) => fn());
}

/** Apply a full appearance (scheme plus banner) from the server or a live snapshot. */
export function applyAppearance(a) {
  if (!a) return;
  applyScheme(a.scheme);
  setBanner(a);
}

export function useBanner() {
  return useSyncExternalStore((fn) => { listeners.add(fn); return () => listeners.delete(fn); }, () => banner);
}

/** Apply the last-used scheme instantly (no flash), then confirm with the server. */
export function initScheme() {
  let saved = null;
  try { saved = localStorage.getItem(KEY); } catch { /* ignore */ }
  applyScheme(saved || "neon");
  try { setBanner(JSON.parse(localStorage.getItem(BANNER_KEY) || "null")); } catch { /* ignore */ }
  fetch("/api/public/appearance")
    .then((r) => (r.ok ? r.json() : null))
    .then((d) => applyAppearance(d))
    .catch(() => {});
}
