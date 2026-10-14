const CACHE_NAME = 'brvm-app-v2';
const FILES_TO_CACHE = ['./', './index.html', './manifest.json'];
// Ces fichiers changent chaque jour (cours, dividendes) : on doit toujours
// essayer le reseau en premier, sinon on affiche des prix perimes meme
// quand internet marche tres bien.
const DONNEES_FRAICHES = ['cours-auto.json', 'dividendes-auto.json'];

function estDonneeFraiche(url) {
  return DONNEES_FRAICHES.some(function (nom) { return url.indexOf(nom) !== -1; });
}

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

  // Cours et dividendes : reseau d'abord (toujours la donnee du jour des
  // qu'internet est disponible), cache uniquement si hors-ligne.
  if (estDonneeFraiche(event.request.url)) {
    event.respondWith(
      fetch(event.request).then(function(response) {
        if (response && response.status === 200) {
          const clone = response.clone();
          caches.open(CACHE_NAME).then(function(cache){ cache.put(event.request, clone); });
        }
        return response;
      }).catch(function() {
        return caches.match(event.request);
      })
    );
    return;
  }

  // Reste de l'app (HTML, manifest, icones...) : cache d'abord pour un
  // chargement instantane et un fonctionnement hors-ligne, avec mise a jour
  // silencieuse du cache en arriere-plan.
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
