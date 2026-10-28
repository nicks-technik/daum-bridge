const CACHE_NAME = 'daum-bridge-v1';
self.addEventListener('install', (event) => {
  self.skipWaiting();
});
self.addEventListener('activate', (event) => {
  event.waitUntil(clients.claim());
});
self.addEventListener('fetch', (event) => {
  // Simple pass-through
  event.respondWith(fetch(event.request));
});
