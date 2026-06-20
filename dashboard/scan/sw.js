/* Golden Coffee Floorplan Scanner — service worker.
   Caches the app shell for offline use. Cache-first for the shell, with a
   network fallback so the app still works with no connectivity. */
const CACHE = 'gc-scan-v1';
const SHELL = [
  './',
  './index.html',
  './app.js',
  './scan3d.js',
  './manifest.webmanifest',
  './icon.svg',
  '../vendor/three.min.js',
];

self.addEventListener('install', (e) => {
  e.waitUntil(
    caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (e) => {
  e.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))
    ).then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (e) => {
  const req = e.request;
  if (req.method !== 'GET') return; // never cache POSTs (e.g. /geometry push)
  const url = new URL(req.url);
  // Only handle same-origin / vendored assets; let cross-origin API calls pass.
  if (url.origin !== self.location.origin) return;
  e.respondWith(
    caches.match(req).then((hit) => {
      if (hit) return hit;
      return fetch(req)
        .then((res) => {
          // Cache successful basic responses for next time.
          if (res && res.status === 200 && res.type === 'basic') {
            const copy = res.clone();
            caches.open(CACHE).then((c) => c.put(req, copy));
          }
          return res;
        })
        .catch(() => caches.match('./index.html'));
    })
  );
});
