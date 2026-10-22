// Install-as-an-app support: the service worker, the install prompt and song alerts.
import { useEffect, useState } from "react";

let deferredPrompt = null;
const listeners = new Set();

export function initPwa() {
  window.addEventListener("beforeinstallprompt", (e) => {
    e.preventDefault(); // show our own "Install app" button instead of the browser's mini bar
    deferredPrompt = e;
    listeners.forEach((fn) => fn(true));
  });
  window.addEventListener("appinstalled", () => {
    deferredPrompt = null;
    listeners.forEach((fn) => fn(false));
  });
  // Service workers need HTTPS (or localhost); on a plain-HTTP LAN address the app still works, just not installed.
  if ("serviceWorker" in navigator && import.meta.env.PROD && window.isSecureContext) {
    window.addEventListener("load", () => navigator.serviceWorker.register("/sw.js").catch(() => {}));
  }
}

const isStandalone = () => window.matchMedia?.("(display-mode: standalone)").matches || window.navigator.standalone;
const isIos = () => /iphone|ipad|ipod/i.test(window.navigator.userAgent);

/** { canInstall, install, iosHint } for an "Install app" button. */
export function useInstall() {
  const [available, setAvailable] = useState(!!deferredPrompt);
  useEffect(() => {
    listeners.add(setAvailable);
    return () => listeners.delete(setAvailable);
  }, []);
  const install = async () => {
    if (!deferredPrompt) return;
    deferredPrompt.prompt();
    await deferredPrompt.userChoice.catch(() => null);
    deferredPrompt = null;
    setAvailable(false);
  };
  return { canInstall: available, install, iosHint: !available && isIos() && !isStandalone() };
}

export const alertsSupported = () => "Notification" in window && window.isSecureContext;

/** A system notification, only when the page isn't on screen (the in-page toast covers the rest). */
export async function notify(title, body) {
  if (!alertsSupported() || Notification.permission !== "granted" || !document.hidden) return;
  const options = { body, icon: "/icon-192.png", badge: "/icon-192.png", tag: "karoulette", renotify: true,
    vibrate: [300, 150, 300] };
  try {
    const reg = await navigator.serviceWorker?.getRegistration();
    if (reg) await reg.showNotification(title, options);
    else new Notification(title, options); // eslint-disable-line no-new
  } catch { /* the toast and vibration still happen */ }
}
