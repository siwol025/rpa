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

백엔드 `backend/docs/api/convention.md` v0.1 (API 규약)을 따른다. 2026-11-24 기준 `feat/api-convention` 브랜치에 있고 `main`에 합쳐지기 전이다.

- 에러는 `{code, message, detail}`. 화면에는 `message`, 분기는 `code`로 한다
- 유형은 코드(`INQUIRY` 등)로 주고받고 한글 이름은 `src/lib/status.ts`에서 붙인다. 나중에 추가된 값은 코드를 그대로 보여준다
- 정렬은 `sort=-call_datetime` 형식. 서버 기본값이 등록순이라 목록은 정렬을 항상 보낸다
- 여러 값은 같은 이름을 반복한다 (`?status=FAILED&status=QUEUED`)
- `page` 최대 10000, `size` 최대 100
- 정체 여부는 `is_stale`, 정체 필터는 `stale`

## 백엔드 확인이 필요한 것

규약에 없어 임시로 정했다. 목록은 `src/api/types.ts` 맨 위와 `src/api/uploads.ts`에 있다.

1. 목록 항목의 필드, 상세 응답의 구조와 로그의 이름
2. 상세 응답에도 `is_stale`이 있는지
3. 검토 완료를 알리는 필드 (`PATCH`의 `review_completed`)
4. 통계 응답의 필드
5. 업로드 폼의 필드 이름 (`files`)
