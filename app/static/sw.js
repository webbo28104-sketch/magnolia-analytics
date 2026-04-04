// Magnolia Analytics — minimal service worker
// Required for Android Chrome "Add to Home Screen" install prompt.
// Strategy: network-first with graceful offline fallback.
'use strict';

var CACHE = 'magnolia-v1';

self.addEventListener('install', function (e) {
  // Activate immediately without waiting for old tabs to close
  e.waitUntil(self.skipWaiting());
});

self.addEventListener('activate', function (e) {
  // Take control of all open clients and clean up old caches
  e.waitUntil(
    caches.keys().then(function (keys) {
      return Promise.all(
        keys.filter(function (k) { return k !== CACHE; })
            .map(function (k) { return caches.delete(k); })
      );
    }).then(function () { return self.clients.claim(); })
  );
});

self.addEventListener('fetch', function (e) {
  // Only handle GET navigation requests — let everything else pass through
  if (e.request.method !== 'GET') return;
  if (e.request.mode !== 'navigate') return;

  e.respondWith(
    fetch(e.request).catch(function () {
      return caches.match('/') || Response.error();
    })
  );
});
