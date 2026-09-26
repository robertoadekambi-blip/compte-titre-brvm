const CACHE_NAME = 'brvm-app-v1';
const FILES_TO_CACHE = ['./', './index.html', './manifest.json'];

self.addEventListener('install', function(event) {
  self.skipWaiting();
  event.waitUntil(caches.open(CACHE_NAME).then(function(cache) {
    return cache.addAll(FILES_TO_CACHE);
  }));
});

self.addEventListener('activate', function(event) {
  event.waitUntil(caches.keys().then(function(keys) {
    return Promise.all(keys.filter(function(k){return k!==CACHE_NAME;}).map(function(k){return caches.delete(k);}));
  }));
  self.clients.claim();
});

self.addEventListener('fetch', function(event) {
  if (event.request.method !== 'GET') return;
  event.respondWith(caches.match(event.request).then(function(cached) {
    const networkFetch = fetch(event.request).then(function(response) {
      if (response && response.status === 200 && event.request.url.indexOf(self.location.origin) === 0) {
        const clone = response.clone();
        caches.open(CACHE_NAME).then(function(cache){ cache.put(event.request, clone); });
      }
      return response;
    }).catch(function(){ return cached; });
    return cached || networkFetch;
  }));
});
