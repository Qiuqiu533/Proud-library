const CACHE_NAME = 'proud-library-v39';
const STATIC_ASSETS = [
  '/',
  '/static/app.js',
  '/static/extras.js',
  '/static/style.css',
  '/static/icons/icon-192.png',
  '/static/icons/icon-512.png',
  '/static/icons/apple-touch-icon.png',
  'https://fonts.googleapis.com/css2?family=Noto+Sans+JP:wght@300;400;500;700&display=swap',
  'https://cdnjs.cloudflare.com/ajax/libs/qrcodejs/1.0.0/qrcode.min.js',
];

self.addEventListener('install', e => {
  self.skipWaiting();
  e.waitUntil(
    caches.open(CACHE_NAME).then(cache => cache.addAll(STATIC_ASSETS).catch(() => {}))
  );
});

self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys()
      .then(keys => Promise.all(keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k))))
      .then(() => clients.claim())
  );
});

self.addEventListener('fetch', e => {
  const url = new URL(e.request.url);

  // APIリクエストは常にネットワークから取得（キャッシュしない）
  if (url.pathname.startsWith('/api/') || url.pathname === '/ping') {
    e.respondWith(fetch(e.request));
    return;
  }

  // 静的ファイル: キャッシュ優先、なければネットワーク
  e.respondWith(
    caches.match(e.request).then(cached => cached || fetch(e.request))
  );
});
