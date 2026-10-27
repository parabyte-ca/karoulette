// Guided tours: shown once per phone or browser, replayable from Help. Seen tours are kept in localStorage.
const KEY = "kq_tours_seen";

const seen = () => {
  try { return JSON.parse(localStorage.getItem(KEY) || "{}"); } catch { return {}; }
};
const save = (tours) => {
  try { localStorage.setItem(KEY, JSON.stringify(tours)); } catch { /* private mode: the tour shows again */ }
};

/** Browsers driven by test tools skip tours unless a test asks for them (localStorage kq_tours = "on"). */
const automated = () => {
  try { return navigator.webdriver && localStorage.getItem("kq_tours") !== "on"; } catch { return !!navigator.webdriver; }
};

export const shouldShowTour = (name) => !automated() && !seen()[name];
export const markTourSeen = (name) => save({ ...seen(), [name]: Date.now() });
export const resetTours = (...names) => {
  const tours = seen();
  names.forEach((n) => delete tours[n]);
  save(tours);
};
