# ⏰ FlexTime - 유연근무 출퇴근 관리 앱

## 🚀 실행 방법

### 1. 의존성 설치
```bash
pip install -r requirements.txt
```

### 2. 회사 위치 설정 (중요!)
`main.py` 파일 상단의 `COMPANY_SETTINGS`에서 회사 좌표를 설정하세요:

```python
COMPANY_SETTINGS = {
    "latitude": 35.1595,      # 회사 위도 ← 여기 수정!
    "longitude": 126.8526,    # 회사 경도 ← 여기 수정!
    "radius_meters": 200,     # 허용 반경 (미터)
    ...
}
```

**회사 좌표 찾는 방법:**
1. Google Maps에서 회사 검색
2. 지도에서 회사 위치 우클릭
3. 첫 번째 숫자가 위도, 두 번째가 경도

### 3. 서버 실행
```bash
python main.py
```
또는
```bash
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

### 4. 접속
브라우저에서 `http://localhost:8000` 접속

### 5. 모바일에서 사용하기
1. 같은 WiFi 네트워크에서 컴퓨터 IP 확인 (예: 192.168.0.10)
2. 모바일 브라우저에서 `http://192.168.0.10:8000` 접속
3. "홈 화면에 추가" 선택 → 앱처럼 사용!

---

## 📱 기능 목록

| 기능 | 설명 |
|------|------|
| ✅ 출근/퇴근 | GPS 위치 확인 후 출퇴근 기록 |
| ✅ 근무시간 | 오늘/이번 주 근무시간 실시간 확인 |
| ✅ 일정 관리 | 출퇴근 예정시간 설정 |
| ✅ 팀 현황 | 같은 팀원들 출퇴근 상태 확인 |
| ✅ 휴가 관리 | 연차/반차 등록 및 잔여 연차 확인 |
| ✅ 기록 수정 | 퇴근 깜빡했을 때 수정 가능 |

---

## 🗂️ 파일 구조

```
flextime/
├── main.py              # 백엔드 API (FastAPI)
├── requirements.txt     # 의존성
├── flextime.db         # SQLite DB (자동 생성)
├── templates/
│   └── index.html      # 프론트엔드 (전체 기능)
└── static/
    └── manifest.json   # PWA 설정
```

---

## 🔧 추후 커스터마이징

### 팀 추가
`main.py`의 `init_db()` 함수에서:
```python
c.execute("INSERT OR IGNORE INTO team (name) VALUES ('마케팅팀')")
```

### 기본 출퇴근 시간 변경
`COMPANY_SETTINGS`에서:
```python
"default_in": "09:00",   # 기본 출근
"default_out": "18:00",  # 기본 퇴근
```

---

## 🌐 배포 (선택사항)

### 무료 배포 옵션
1. **Railway** (추천): railway.app
2. **Render**: render.com  
3. **Fly.io**: fly.io

배포 후 HTTPS 주소로 접속하면 PWA 설치 가능!

---

## 📞 문의
문제가 있으면 알려주세요!
