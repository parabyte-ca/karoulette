import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from "react";

let apiPromise = null;
function loadYouTubeApi() {
  if (window.YT && window.YT.Player) return Promise.resolve(window.YT);
  if (apiPromise) return apiPromise;
  apiPromise = new Promise((resolve) => {
    const prev = window.onYouTubeIframeAPIReady;
    window.onYouTubeIframeAPIReady = () => {
      prev?.();
      resolve(window.YT);
    };
    const tag = document.createElement("script");
    tag.src = "https://www.youtube.com/iframe_api";
    document.head.appendChild(tag);
  });
  return apiPromise;
}

/**
 * Official YouTube IFrame Player. Plays on youtube.com (not -nocookie) so the browser's
 * YouTube Premium sign-in applies. Reports `ended` and `error` (codes 2, 5, 100, 101, 150).
 */
const YouTubePlayer = forwardRef(function YouTubePlayer({ videoId, itemId, onEnded, onError, onStateChange }, ref) {
  const host = useRef(null);
  const player = useRef(null);
  const current = useRef({ itemId, onEnded, onError, onStateChange });
  const [ready, setReady] = useState(false);
  current.current = { itemId, onEnded, onError, onStateChange };

  useImperativeHandle(ref, () => ({
    play: () => player.current?.playVideo?.(),
    pause: () => player.current?.pauseVideo?.(),
    toggle: () => {
      const p = player.current;
      if (!p?.getPlayerState) return;
      if (p.getPlayerState() === 1) p.pauseVideo(); else p.playVideo();
    },
    restart: () => player.current?.seekTo?.(0, true),
    state: () => player.current?.getPlayerState?.() ?? -1,
  }));

  useEffect(() => {
    let cancelled = false;
    loadYouTubeApi().then((YT) => {
      if (cancelled || !host.current) return;
      player.current = new YT.Player(host.current, {
        width: "100%",
        height: "100%",
        playerVars: { autoplay: 1, rel: 0, playsinline: 1, modestbranding: 1, fs: 0, iv_load_policy: 3 },
        events: {
          onReady: () => setReady(true),
          onStateChange: (e) => {
            current.current.onStateChange?.(e.data);
            if (e.data === YT.PlayerState.ENDED) current.current.onEnded?.(current.current.itemId);
          },
          onError: (e) => current.current.onError?.(current.current.itemId, e.data),
        },
      });
    });
    return () => {
      cancelled = true;
      try { player.current?.destroy?.(); } catch { /* ignore */ }
    };
  }, []);

  useEffect(() => {
    if (!ready || !player.current) return;
    if (videoId) player.current.loadVideoById(videoId);
    else player.current.stopVideo();
  }, [ready, videoId, itemId]);

  return (
    <div className="player-frame">
      <div ref={host} />
    </div>
  );
});

export default YouTubePlayer;
