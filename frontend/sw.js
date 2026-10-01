/**
 * Jummikville Academy Fee Management System — Service Worker
 *
 * This service worker enables the app to be installed as a PWA (Progressive
 * Web App). It caches the app shell so the login screen loads instantly even
 * on a slow connection, and shows a friendly offline page when there's no
 * network at all.
 *
 * STRATEGY: Network-first for API calls (always fresh data), cache-first for
 * static assets (fast loads).
 */

const CACHE_VERSION = "jummikville-v1";
const STATIC_CACHE  = `${CACHE_VERSION}-static`;
const API_PREFIX    = "/api/";

// App shell files to cache on install — these make the login screen load
// offline and the app feel instant.
const APP_SHELL = [
  "/",
  "/app.js",
  "/manifest.json",
  "/assets/images/icon-512.jpg",
  "/assets/images/icon-192.jpg",
  "/assets/images/jummikville_logo.jpeg",
];

// ── Install: cache the app shell ─────────────────────────────────────────────
self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(STATIC_CACHE).then((cache) => {
      // addAll fails silently for missing files — only critical shell assets
      // should be here. Non-critical assets are cached lazily on first fetch.
      return cache.addAll(APP_SHELL).catch((err) => {
        console.warn("[SW] App shell pre-cache partial failure:", err);
      });
    })
  );
  // Take control immediately without waiting for the old SW to finish.
  self.skipWaiting();
});

// ── Activate: clean up old caches ────────────────────────────────────────────
self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(
        keys
          .filter((key) => key !== STATIC_CACHE)
          .map((key) => caches.delete(key))
      )
    )
  );
  // Claim all open clients (tabs) immediately.
  self.clients.claim();
});

// ── Fetch: route requests ─────────────────────────────────────────────────────
self.addEventListener("fetch", (event) => {
  const { request } = event;
  const url = new URL(request.url);

  // --- API calls: network-only (never serve stale financial data) ---
  if (url.pathname.startsWith(API_PREFIX)) {
    event.respondWith(
      fetch(request).catch(() =>
        new Response(
          JSON.stringify({ detail: "You appear to be offline. Please check your connection." }),
          { status: 503, headers: { "Content-Type": "application/json" } }
        )
      )
    );
    return;
  }

  // --- Static assets: cache-first, then network (stale-while-revalidate) ---
  event.respondWith(
    caches.match(request).then((cached) => {
      const networkFetch = fetch(request)
        .then((response) => {
          // Cache successful GET responses for static files.
          if (
            response.ok &&
            request.method === "GET" &&
            !url.pathname.startsWith(API_PREFIX)
          ) {
            const clone = response.clone();
            caches.open(STATIC_CACHE).then((cache) => cache.put(request, clone));
          }
          return response;
        })
        .catch(() => {
          // No network and no cache — return the cached root as fallback.
          if (request.mode === "navigate") {
            return caches.match("/");
          }
          return new Response("Offline", { status: 503 });
        });

      // Return cached version immediately; update in background.
      return cached || networkFetch;
    })
  );
});
