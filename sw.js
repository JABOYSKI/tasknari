const CACHE = 'tasknari-~0,12';
const ASSETS = [
  '/tasknari/',
  '/tasknari/index.html',
  '/tasknari/manifest.json',
  '/tasknari/icon-192.png',
  '/tasknari/icon-512.png'
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

self.addEventListener('fetch', e => {
  e.respondWith(
    caches.match(e.request).then(r => r || fetch(e.request))
  );
});
