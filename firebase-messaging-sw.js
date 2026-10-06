// Service worker dedie aux notifications Firebase Cloud Messaging.
// Doit rester a la racine du depot (meme niveau que index.html).
// La configuration Firebase doit etre IDENTIQUE a celle de index.html.

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

var messaging = firebase.messaging();

messaging.onBackgroundMessage(function(payload){
  var title = (payload.notification && payload.notification.title) || 'Alerte BRVM';
  var body = (payload.notification && payload.notification.body) || '';
  self.registration.showNotification(title, {
    body: body,
    icon: './icons/icon-192.png'
  });
});
