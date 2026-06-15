const CACHE_VERSION = 'v2';
self.addEventListener('install', e => {
  self.skipWaiting();
  e.waitUntil(caches.delete(CACHE_VERSION));
});
self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys().then(keys => Promise.all(keys.map(k => caches.delete(k))))
      .then(() => clients.claim())
  );
});
self.addEventListener('fetch', e => e.respondWith(fetch(e.request)));
