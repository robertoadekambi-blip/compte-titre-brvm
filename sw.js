// Service worker UNIQUE de l'app : il gere a la fois
//  1) le fonctionnement hors-ligne (cache), et
//  2) l'affichage des notifications d'alertes de prix (Firebase Cloud Messaging).
// Avant, deux service workers (sw.js et firebase-messaging-sw.js) se disputaient
// la meme place : a chaque ouverture de l'app, l'un remplacait l'autre. Resultat :
// les notifications n'arrivaient plus, et l'app restait bloquee sur une vieille
// version en cache. Un seul service worker regle les deux problemes.

const CACHE_NAME = 'brvm-app-v3';
const FILES_TO_CACHE = ['./', './index.html', './manifest.json'];
const NETWORK_TIMEOUT_MS = 4000;

/* ---------- notifications (Firebase Cloud Messaging) ---------- */
try {
  importScripts('https://cdnjs.cloudflare.com/ajax/libs/firebase/10.11.1/firebase-app-compat.min.js');
  importScripts('https://cdnjs.cloudflare.com/ajax/libs/firebase/10.11.1/firebase-messaging-compat.min.js');
  firebase.initializeApp({
    apiKey: "AIzaSyDjHybPTfZRHT9P2lK3T3_nQLRTYk_w-Uk",
    authDomain: "compte-titre-brvm.firebaseapp.com",
    projectId: "compte-titre-brvm",
    storageBucket: "compte-titre-brvm.firebasestorage.app",
    messagingSenderId: "939191003573",
    appId: "1:939191003573:web:4f261a05a27140f59691fc"
  });
  const messaging = firebase.messaging();
  messaging.onBackgroundMessage(function(payload){
    // Un message qui contient deja une "notification" est affiche automatiquement
    // par Firebase : on ne l'affiche nous-memes que s'il n'en contient pas (sinon doublon).
    if (payload && payload.notification) return;
    const data = (payload && payload.data) || {};
    self.registration.showNotification(data.title || 'Alerte BRVM', {
      body: data.body || '',
      icon: './icons/icon-192.png'
    });
  });
} catch (e) {
  // Pas de reseau au moment de l'installation : le cache hors-ligne marche quand meme.
}

self.addEventListener('notificationclick', function(event){
  event.notification.close();
  event.waitUntil(self.clients.matchAll({type:'window', includeUncontrolled:true}).then(function(list){
    for (const c of list) { if ('focus' in c) return c.focus(); }
    return self.clients.openWindow('./');
  }));
});

/* ---------- cache / hors-ligne ---------- */
self.addEventListener('install', function(event) {
  self.skipWaiting();
  event.waitUntil(caches.open(CACHE_NAME).then(function(cache) {
    return cache.addAll(FILES_TO_CACHE.map(function(u){ return new Request(u, {cache: 'reload'}); }));
  }));
});

self.addEventListener('activate', function(event) {
  event.waitUntil(caches.keys().then(function(keys) {
    return Promise.all(keys.filter(function(k){return k!==CACHE_NAME;}).map(function(k){return caches.delete(k);}));
  }).then(function(){ return self.clients.claim(); }));
});

function reseauDAbord(event) {
  // Toujours la derniere version publiee quand internet marche ; la copie en cache
  // ne sert que hors-ligne (ou si le reseau met plus de 4 s a repondre).
  const depuisReseau = fetch(event.request.url, {cache: 'no-cache'}).then(function(response) {
    if (response && response.status === 200) {
      const clone = response.clone();
      caches.open(CACHE_NAME).then(function(cache){ cache.put(event.request, clone); });
    }
    return response;
  });
  const delai = new Promise(function(resolve){
    setTimeout(function(){
      caches.match(event.request).then(function(c){ if (c) resolve(c); });
    }, NETWORK_TIMEOUT_MS);
  });
  return Promise.race([depuisReseau, delai]).catch(function() {
    return caches.match(event.request).then(function(c){
      return c || caches.match('./index.html');
    });
  });
}

self.addEventListener('fetch', function(event) {
  if (event.request.method !== 'GET') return;
  const memeOrigine = event.request.url.indexOf(self.location.origin) === 0;
  if (memeOrigine) {
    event.respondWith(reseauDAbord(event));
    return;
  }
  // Scripts externes versionnes (Firebase, ExcelJS sur cdnjs) : cache d'abord, ils ne
  // changent jamais. Tout le reste (Firestore, connexion, notifications...) passe
  // directement par le reseau, sans jamais etre mis en cache.
  if (event.request.url.indexOf('https://cdnjs.cloudflare.com/') !== 0) return;
  event.respondWith(caches.match(event.request).then(function(cached) {
    return cached || fetch(event.request).then(function(response) {
      if (response && response.status === 200) {
        const clone = response.clone();
        caches.open(CACHE_NAME).then(function(cache){ cache.put(event.request, clone); });
      }
      return response;
    });
  }));
});
