const CACHE = 'tasknari-~0,12';
// Paths resolve against this sw.js's URL, so they work whether the app is
// served at /tasknari/ (GitHub Pages) or / (localhost).
const ASSETS = [
  './',
  './index.html',
  './manifest.json',
  './icon-192.png',
  './icon-512.png'
];

// Cache all assets first, THEN skip waiting — order matters
self.addEventListener('install', e => {
  e.waitUntil(
    caches.open(CACHE)
      .then(c => c.addAll(ASSETS))
      .then(() => self.skipWaiting())
  );
});

// Delete old caches, claim clients, then notify them to reload
self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys()
      .then(keys => Promise.all(
        keys.filter(k => k !== CACHE).map(k => caches.delete(k))
      ))
      .then(() => self.clients.claim())
      .then(() => self.clients.matchAll({ type: 'window' }))
      .then(clients => clients.forEach(client =>
        client.postMessage({ type: 'SW_UPDATED' })
      ))
  );
});

// Stale-while-revalidate: return the cached response immediately when
// available, but always kick off a background fetch and update the cache so
// the next reload gets fresh content. Falls back gracefully when offline.
self.addEventListener('fetch', e => {
  if (e.request.method !== 'GET') return;
  e.respondWith(
    caches.open(CACHE).then(async cache => {
      const cached = await cache.match(e.request);
      const network = fetch(e.request).then(resp => {
        if (resp && resp.ok) cache.put(e.request, resp.clone());
        return resp;
      }).catch(() => cached);
      return cached || network;
    })
  );
});
