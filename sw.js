const CACHE_NAME = 'srt-labels-v2';
const ASSETS = [
  './index.html',
  './manifest.json',
  './icon.png',
  './icon-192.png',
  './icon-maskable.png'
];

// Install — cache core assets
self.addEventListener('install', e => {
  e.waitUntil(
    caches.open(CACHE_NAME)
      .then(cache => cache.addAll(ASSETS))
      .then(() => self.skipWaiting())
  );
});

// Activate — clean old caches
self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k)))
    ).then(() => self.clients.claim())
  );
});

// Fetch — network first, fallback to cache for the HTML shell
self.addEventListener('fetch', e => {
  // Always fetch API calls fresh — never cache them
  if (e.request.url.includes('/api/')) {
    e.respondWith(fetch(e.request));
    return;
  }

  // For app shell — try network, fall back to cache.
  // ignoreSearch: the app's shortcuts open index.html?tab=queue, which is
  // cached under plain index.html.
  e.respondWith(
    fetch(e.request)
      .then(res => {
        const clone = res.clone();
        caches.open(CACHE_NAME).then(cache => cache.put(e.request, clone));
        return res;
      })
      .catch(() => caches.match(e.request, { ignoreSearch: true }))
  );
});

// Tapping a "print failed" notification brings the app forward on its Queue tab
self.addEventListener('notificationclick', e => {
  e.notification.close();
  e.waitUntil((async () => {
    const wins = await self.clients.matchAll({ type: 'window', includeUncontrolled: true });
    for (const w of wins) {
      if ('focus' in w) {
        w.postMessage({ type: 'open-tab', tab: 'queue' });
        return w.focus();
      }
    }
    return self.clients.openWindow('./index.html?tab=queue');
  })());
});
