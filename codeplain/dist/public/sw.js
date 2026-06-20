const CACHE_NAME = 'gc-v1';
const ASSETS = [
  '/',
  '/index.html',
  '/src/main.tsx',
  '/manifest.json'
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {
      return cache.addAll(ASSETS);
    }).catch(err => {
      console.error(`[SW] Cache install failed: ${err}`);
    })
  );
});

self.addEventListener('fetch', (event) => {
  event.respondWith(
    caches.match(event.request).then((response) => {
      return response || fetch(event.request);
    }).catch(err => {
      console.error(`[SW] Fetch failed for ${event.request.url}: ${err}`);
    })
  );
});