# MARKET BRIEF · cost

모바일 주식 브리핑을 보관하고 GitHub Pages로 게시하는 정적 사이트입니다.
소스 저장소는 `meangyulim/cost`이며, 별도 외부 서버·유료 AI API를 사용하지 않습니다.
GitHub Actions는 정적 사이트 생성·배포와 요청 시 KRX/Massive 일별 자료의 수집·수치 분석을 담당합니다.
시장 뉴스 조사와 AI 작성 예약은 별도 Work 클라우드 기능이 필요합니다.

실제 브리핑과 **TEST · 레이아웃 확인용 자료 · 실제 시세 아님** 보고서를 구분해 보관합니다.
홈은 최신 실제 브리핑을 표시하며, 상단 날짜별 보관함에서 이전 자료를 열 수 있습니다.
2026.10.01 사용자 승인에 따라 이 프로젝트에서 브리핑 갱신을 요청하면 새 회차 작성·게시·검증·카카오톡 나에게 1회 전송을 진행합니다. 자세한 규칙은 `docs/publishing-and-dispatch.md`를 따릅니다.

## 개발과 검증

Python 3.12 이상과 Git을 사용합니다. 사이트 생성에는 외부 패키지가 필요하지 않습니다.
이미 격리된 클라우드 작업 환경의 기존 체크아웃을 사용합니다. 별도 Git worktree는 만들지 않습니다.

```sh
cd /workspace/cost
python3 -m unittest discover -s tests -v
python3 scripts/build_site.py
```

`public/`가 배포 결과입니다. 홈은 최신 실제 보고서를 우선하며, 실제 보고서가 없을 때 TEST를 보여줍니다.
`public/archive/`는 전체 날짜별 목록이고 `public/manifest.json`은 회차와 상대 경로를 제공합니다.
보고서는 `public/reports/<회차 ID>/index.html`에 남습니다.
CSS와 모든 내부 링크는 상대 경로라 프로젝트 Pages 하위 경로에서도 동작합니다.

로컬 확인이 필요하면 `python3 -m http.server 8000 --bind 127.0.0.1 --directory public`을 실행합니다.
이 개발 서버는 클라우드 공개 게시나 Pages 배포를 대신하지 않습니다.
현재 환경에 설치된 Python Playwright와 Chromium으로 모바일 브라우저 검증을 실행할 수 있습니다.

```sh
python3 scripts/verify_browser.py
```

공개 TEST 사이트의 비로그인 브라우저 검증은 `python3 scripts/verify_public.py`로 실행합니다.
현재 클라우드에서는 기본 샌드박스의 인증서 오류 때문에 승인된 샌드박스 밖 실행으로 통과했습니다.
TLS 검증을 유지하고 새 비로그인 브라우저 문맥을 사용합니다.

브라우저 검증은 `/cost/` 경로에서 390/430px, 200% 글자 확대, 한글·가격·KST,
보관함과 회차 탐색을 확인합니다. GitHub Pages의 공개 HTTP/브라우저 검증과는 별개입니다.

## 보고서 추가

`data/reports/test-layout-2026-09-30.json`은 데이터 구조 예시입니다.
실제 보고서는 `is_test: false`로 만들고 아래 규칙을 따릅니다.

- 한국 회차 날짜는 한국 시장 날짜, 미국 회차 날짜는 뉴욕 시장 날짜입니다.
  ID는 `kr-pre-YYYY-MM-DD`, `kr-close-YYYY-MM-DD`, `us-pre-YYYY-MM-DD`, `us-close-YYYY-MM-DD`입니다.
  수동 장중 갱신은 `kr-intraday-YYYY-MM-DD-HHMM`으로 같은 날짜의 여러 요청을 구분합니다. HHMM은 `as_of`의 KST 시각과 일치해야 합니다. 기존 `kr-intraday-YYYY-MM-DD` 회차도 유효합니다.
- `as_of`는 데이터 기준 시각, `queried_at`은 조회 시각입니다. 날짜와 `+09:00`을 반드시 포함합니다.
- 지수는 값·단위·전일 대비 포인트·등락률, 종목은 가격·통화·변동액·등락률·시각·거래구간·출처를 포함합니다.
- 장후는 해당 거래일 정규장 종가, 장전은 전일 정규장 종가를 기본으로 합니다. 별도 장전/시간외 가격은 섞지 않습니다.
- 원문의 정밀도를 유지합니다. 확인하지 못한 가격은 `미확인`, `direction: missing`, `missing_reason`으로 남깁니다.
  확인된 가격처럼 역산하지 않습니다.
- 각 지수·종목·이슈·환율의 `source`는 `sources` 항목에 연결합니다.
  실제 자료의 `url`은 원문 HTTPS 링크이고 `note`에는 원자료 기준 시각과 범위를 남깁니다.
- 실제 보고서는 `calendar_evidence`에 공식 달력의 `url`, `market_date`,
  `is_trading_day: true`, `early_close`, `checked_at`, `note`가 필요합니다. 휴장일에는 게시하지 않습니다.
- 이슈 3개, 매회 새로 선정한 관찰 종목 3개, 다음 확인 순서 2~3개를 작성합니다.
  확정된 발표 시각을 쓰려면 날짜 포함 KST를 표시하고 원문 근거를 확인합니다.
- 사실·해석을 구분합니다. 중요한 불확실성은 본문에 표시하고 긴 계산만 접습니다.

빌더는 형식과 링크 연결을 검사합니다. **시세의 진위, 출처의 내용, 실제 거래일을 자동 검증하지 않습니다.**
게시 작성자가 원문을 읽고 시장·날짜·거래구간을 대조해야 합니다.

```sh
python3 scripts/add_report.py /path/to/verified-new-report.json
python3 -m unittest discover -s tests -v
python3 scripts/build_site.py
```

추가 명령은 같은 회차 파일이 존재하면 실패하여 원본을 덮어쓰지 않습니다.
기존 원본과 과거 보고서를 수정하거나 삭제하지 않습니다. 전체 `public/`를 배포해 과거 글을 유지합니다.
원격 동시 실행 충돌은 일반 Git fast-forward 검사로 처리하며 force push하지 않습니다.

## GitHub Pages 연결

저장소 공개 범위와 계정 플랜을 먼저 확인합니다. 공개 저장소의 일반 GitHub Pages는 무료지만
비공개 저장소는 계정 플랜 지원을 확인해야 합니다. 이 작업은 저장소 공개 범위를 자동 변경하지 않습니다.
Pages에 올리는 보고서는 공개 자료여야 하며 개인정보·토큰·카카오 대화·비공개 원문을 포함하지 않습니다.

1. 검토된 변경을 기본 브랜치 `main`에 반영합니다.
2. 저장소 Settings → Pages → Build and deployment → Source에서 **GitHub Actions**를 선택합니다.
3. Actions의 `Deploy static briefing site`를 실행하거나 `main`에 push합니다.
4. 해당 커밋의 배포 성공과 GitHub가 반환하는 실제 Pages URL을 확인합니다.
   계정과 저장소명으로 예상 URL을 만들어 배포 성공으로 취급하지 않습니다.
5. 실제 회차 URL에 인증·쿠키 없는 HTTP GET과 비로그인 브라우저 검증을 수행합니다.
   HTTP 200, 로그인 이동 없음, TEST 표시, 한글·가격·날짜 포함 KST·근거·보관함을 확인합니다.

Git 읽기 성공은 API/쓰기/Pages 배포 권한을 증명하지 않습니다.
초기에는 API 접근이 네트워크 프록시에서 차단됐으나 이후 실제 API 읽기가 성공했습니다.
Git 읽기·쓰기, 브랜치 및 `main` 반영, TEST의 Actions 배포 성공을 확인했습니다.
GitHub Pages API가 반환한 실제 주소는 **https://meangyulim.github.io/cost/**입니다.
홈과 `reports/test-layout-2026-09-30/`는 익명 HTTP 200을 반환하며 공개 HTML이 검증한 빌드와 일치합니다.
사용자 브라우저에서 열리는 것도 확인받았습니다. 클라우드 비로그인 브라우저 검증도 390/430px, 200% 글자 확대,
보관함·회차·출처 탐색까지 통과했습니다. TLS 검증을 끄지 않았습니다.
기본 샌드박스 Chromium은 `ERR_CERT_AUTHORITY_INVALID`를 반환했지만 승인된 샌드박스 밖 실행에서는 통과했습니다.
플랫폼 CA의 영구 등록은 사용자 승인 후 실행했습니다. 동일한 CA가 이미 신뢰 저장소에 있어 추가 신뢰 항목은 생기지 않았습니다.
사용자가 Pages Source를 변경했고 API의 `build_type: workflow`로 GitHub Actions 방식을 확인했습니다.
인터넷 허용 초안에는 `api.github.com`과 `meangyulim.github.io`를 저장했고 기존 패키지 관리자 설정을 유지했습니다.
이후 실제 API와 공개 사이트 GET은 성공했습니다. 초안 저장과 실행 환경 적용은 별도 동작입니다.
토큰 값을 코드나 채팅에 넣지 않습니다.

## KRX 분석

승인된 KOSPI/KOSDAQ/KRX 지수, 유가증권/코스닥 종목, ETF 일별 API를 활용합니다.
`KRX_API_KEY`를 Actions Secrets에 한 번 등록하면 `Collect KRX briefing inputs` 워크플로로
65거래일 추세, 시장 폭, 거래대금, 지수/ETF 상대 강도를 계산합니다. 요청 파일의 push로도 실행할 수 있습니다.
원시 전체 자료와 키는 게시하지 않으며 예측 확률은 검증 전 제공하지 않습니다.
설정·실행·브리핑 반영 규칙은 [docs/krx-analysis.md](docs/krx-analysis.md)에 있습니다.
2026.10.01 Secrets 등록과 GitHub의 실제 65거래일 수집·분석·산출물 다운로드를 검증했습니다.

## 예약과 카카오톡

미국 분석은 `MASSIVE_API_KEY`를 Actions Secrets에 등록한 뒤 `Collect US briefing inputs`로 실행합니다.
시장 ETF 추세·업종 상대 강도·전체 증권 시장 폭·관찰 종목 정규장 가격을 수집합니다.
설정과 실제 반환 자료 확인 규칙은 [docs/massive-analysis.md](docs/massive-analysis.md)에 있습니다.

예약 시간과 실행 규칙은 [docs/cloud-schedules.md](docs/cloud-schedules.md)에 있습니다.
Work 클라우드 예약 도구와 시장 조사·GitHub 쓰기·배포 조회·공개 브라우저 검증 능력이 실제로 제공되어야 합니다.
현재 세션에는 Work 예약 도구와 PlayMCP 카카오톡 도구가 없으며, 예약은 생성하지 않았습니다.
GitHub Actions cron이나 로컬 PC 예약으로 대체하지 않습니다.

이전 계정 예약 4개는 사용자가 중지했다고 확인했습니다. 중복 실행 정리 조건은 충족됐습니다.
현재 단계에서는 실제 시장 브리핑, 카카오톡 시험 발송, 기존 계정 예약 변경을 수행하지 않습니다.
지속 상태와 중복 발송 방지 규칙은 [docs/publishing-and-dispatch.md](docs/publishing-and-dispatch.md)를 따릅니다.
