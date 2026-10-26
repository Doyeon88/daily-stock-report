// Firebase 콘솔 → 프로젝트 설정 → 일반 → 내 앱(웹) 의 firebaseConfig 값을 채우세요.
// 이 값들과 VAPID 키는 공개용이라 저장소에 올려도 안전합니다 (서비스 계정 키와 다릅니다).
self.FIREBASE_CONFIG = {
  apiKey: "여기에_apiKey",
  projectId: "여기에_projectId",
  messagingSenderId: "여기에_messagingSenderId",
  appId: "여기에_appId",
};

// 프로젝트 설정 → Cloud Messaging → 웹 푸시 인증서 → 키 쌍 생성 으로 얻은 "키 쌍" 값
self.FIREBASE_VAPID_KEY = "여기에_VAPID_키";
