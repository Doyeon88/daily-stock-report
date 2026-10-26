// 백그라운드(페이지가 닫혀 있을 때) 푸시 알림을 표시하는 서비스 워커
importScripts('https://www.gstatic.com/firebasejs/10.12.2/firebase-app-compat.js');
importScripts('https://www.gstatic.com/firebasejs/10.12.2/firebase-messaging-compat.js');
importScripts('./firebase-config.js');

firebase.initializeApp(self.FIREBASE_CONFIG);
// notification 필드가 있는 메시지는 SDK가 자동으로 알림을 띄웁니다.
firebase.messaging();
