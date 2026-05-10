/* Self-destruct: unregister and clear all caches on activate.
   This ensures browsers pick up fresh assets after code changes.
   Re-enable caching by reverting this block and bumping CACHE version. */
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys().then((names) => Promise.all(names.map((n) => caches.delete(n))))
      .then(() => self.clients.matchAll())
      .then((clients) => clients.forEach((c) => c.navigate(c.url)))
  );
  self.registration.unregister();
});
return;

const CACHE = "studyctl-v10";
const ASSETS = [
  "/", "/style.css", "/components.js", "/manifest.json",
  "/vendor/js/htmx-2.0.4.min.js", "/vendor/js/htmx-ext-sse-2.2.2.js",
  "/vendor/js/alpine-3.14.8.min.js", "/vendor/css/opendyslexic-400.css",
  "/vendor/css/inter.css", "/vendor/css/files/inter-latin.woff2",
  "/vendor/css/files/inter-latin-ext.woff2",
];

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
