const CACHE = "studyctl-v2";
const ASSETS = ["/", "/style.css", "/app.js", "/manifest.json", "/session.html"];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(ASSETS)));
  self.skipWaiting();
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys().then((names) =>
      Promise.all(names.filter((n) => n !== CACHE).map((n) => caches.delete(n)))
    )
  );
  self.clients.claim();
});

self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);

  /* Never cache API calls */
  if (url.pathname.startsWith("/api/")) return;

  /* Never cache SSE streams (session/stream) */
  if (e.request.headers.get("Accept") === "text/event-stream") return;

  /* Never cache HTMX fragment requests */
  if (e.request.headers.get("HX-Request")) return;

  e.respondWith(
    caches.match(e.request).then((r) => r || fetch(e.request))
  );
});
