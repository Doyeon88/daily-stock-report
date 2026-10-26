// Firebase 콘솔 → 프로젝트 설정 → 일반 → 내 앱(웹) 의 firebaseConfig 값을 채우세요.
// 이 값들과 VAPID 키는 공개용이라 저장소에 올려도 안전합니다 (서비스 계정 키와 다릅니다).
self.FIREBASE_CONFIG = {
  apiKey: "AIzaSyArW_QDt9gIttgfT5PbKcw_G7wKjRBmmCM",
  projectId: "daily-stock-report-56572",
  messagingSenderId: "623433096545",
  appId: "1:623433096545:web:f788c1f8452cd2d9e2b920",
};

// 프로젝트 설정 → Cloud Messaging → 웹 푸시 인증서 → 키 쌍 생성 으로 얻은 "키 쌍" 값
self.FIREBASE_VAPID_KEY = "BKznNN2Ep_jUIyZ9j6bj9WSNcjPQb1oMn4iHrIxz5Hpq712tzmesZDPMGyRvfjytqvZUA9_sbxVODF9LMFVe5LQ";
