# 콜센터 인공지능 비서 — 프론트엔드

관리자 웹 (로그인 없음). 기능 목록은 `../features_frontend.md`, 화면 시안은 `../design/dashboard-mockup-v0.2.html`.

## 실행

```powershell
npm install
npm run dev        # http://localhost:5173, 예시 데이터 (백엔드 필요 없음)
npm run dev:api    # 실제 백엔드에 연결 (/api → http://localhost:8000)
npm test           # 테스트
npm run build      # 배포용 빌드 (dist/). 예시 데이터는 들어가지 않는다
```

예시 데이터에서 저장·삭제한 내용은 새로고침하면 처음으로 돌아온다.

## 환경변수 (모두 선택)

| 이름 | 기본값 | 설명 |
|---|---|---|
| `VITE_API_BASE_URL` | `/api` | API 주소. 배포할 때 백엔드가 다른 서버면 지정 |
| `VITE_PROXY_TARGET` | `http://localhost:8000` | `dev:api`에서 `/api`를 넘길 백엔드 주소 (셸 환경변수) |

팀 저장소의 `.gitignore`와 pre-commit이 `.env.*`를 막으므로 `.env` 파일 없이 동작하게 했다.

## 폴더

| 위치 | 내용 |
|---|---|
| `src/api/` | API 타입, 호출 함수, TanStack Query 훅. **화면에서 fetch를 직접 쓰지 않는다** |
| `src/mocks/` | 예시 상담 27건과 MSW 핸들러 |
| `src/lib/` | 상태 이름과 재처리 조건, 날짜, 업로드 검사, 추이 계산, 주소의 필터 값 |
| `src/components/` | 레이아웃, 배지, 차트, 에러·빈 상태, 알림 |
| `src/pages/` | 대시보드, 상담 목록, 상담 상세, 업로드·처리 상태, 404 |

## 백엔드와 맞춘 것

백엔드 `backend/docs/api/convention.md` v0.1 (API 규약)을 따른다. 목록·상세·통계 추이·통계 분류는 `main`(`7e3eab1`)의 `backend/docs/api/openapi.json`과 대조했고, 그 FastAPI 앱에 연결해 확인했다 (DB 조회만 메모리 데이터로 바꿈. 실제 PostgreSQL로는 아직 확인하지 않음).

- 에러는 `{code, message, detail}`. 화면에는 `message`, 분기는 `code`로 한다
- 유형은 코드(`INQUIRY` 등)로 주고받고 한글 이름은 `src/lib/status.ts`에서 붙인다. 나중에 추가된 값은 코드를 그대로 보여준다
- 정렬은 `sort=-call_datetime` 형식. 서버 기본값이 등록순이라 목록은 정렬을 항상 보낸다
- 여러 값은 같은 이름을 반복한다 (`?status=FAILED&status=QUEUED`)
- `page` 최대 10000, `size` 최대 100
- 정체 여부는 `is_stale`, 정체 필터는 `stale`. 정체 감지(R-11)가 생기기 전에는 응답에 없고 필터도 무시되므로, 그동안 화면은 정체 조건을 막고 정체 표시를 하지 않는다
- 시작일이 종료일보다 늦거나 2000~2100년 밖이면 서버가 422를 주므로 보내지 않고 안내한다. 키워드는 100자까지
- 후속 조치 여부와 조치 상태는 비어 있을 수 있다 (`-`로 표시)
- 전사 구간은 `start_sec`·`end_sec`(소수 초), 화자는 `AGENT`·`CUSTOMER`·`UNKNOWN`. 개체명은 `[{type, value}]` 배열이고 모르는 종류는 코드를 그대로 보여준다
- 개인정보 표시는 `***`와 `[PHONE]` 같은 STT 표시를 강조한다
- 통계 분류에서 담당자·고객사가 없는 상담은 `name`이 `null`인 한 행이다. 대시보드는 "미지정", 목록의 선택지에서는 뺀다
- 통계 추이는 구간이 400개를 넘으면 422(`range_too_large`). 단위를 바꾸라고 안내한다

## 백엔드 확인이 필요한 것

아직 API가 없어 임시로 정했다. 목록은 `src/api/types.ts` 맨 위와 `src/api/uploads.ts`에 있다.

1. 검토 완료를 알리는 필드 (`PATCH`의 `review_completed`)
2. 통계 요약(`/stats/summary`) 응답의 필드
3. 업로드 폼의 필드 이름 (`files`)
