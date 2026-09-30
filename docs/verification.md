# 게시 검증 기록

이전 계정 네 예약은 사용자가 중지했다고 확인했습니다. 새 예약은 생성하지 않았습니다.

| 항목 | 실제 결과 |
|---|---|
| 저장소 | `meangyulim/cost`, GitHub API 확인, 공개 |
| Git 읽기·쓰기 | 성공, `main` 반영 확인 |
| GitHub가 반환한 Pages URL | https://meangyulim.github.io/cost/ |
| 검증한 배포 커밋 | `1f3f4b50c4ae9cb1519e13f4f8e7a06e65c61a9b` |
| 해당 커밋의 Actions 배포 | [run 36732702551](https://github.com/meangyulim/cost/actions/runs/36732702551), completed/success |
| 홈 익명 HTTP GET | 200, 최종 URL 일치, 인증·쿠키 없음 |
| TEST 회차 익명 HTTP GET | 200, `/cost/reports/test-layout-2026-09-30/`, 인증·쿠키 없음 |
| 공개 HTML 대조 | 홈과 TEST 회차 모두 검증한 로컬 빌드 파일과 바이트 단위 일치 |
| 공개 콘텐츠 | TEST 표시, 한글, 가상 가격 `12,345 KRW`, `2026.09.30 15:30 KST`, 출처 참조 확인 |
| 사용자 브라우저 | 사용자가 사이트 정상 열림을 확인; 비로그인 상태와 세부 검사는 관찰하지 않음 |
| 클라우드 비로그인 브라우저 | 실패, Chromium `ERR_CERT_AUTHORITY_INVALID` |
| 로컬 브라우저 | 별도 검증 통과: 390/430px, 200% 글자 확대, 보관함·회차·출처 탐색 |
| Pages 설정 | `legacy`, source=`main`/`/`; GitHub Actions 전환 필요 |
| Pages 설정 API 변경 | 거절, HTTP 403 `Resource not accessible by integration`; 변경되지 않음 |
| Chromium 신뢰 설정 변경 | 자동 승인 심사 거절; 실제 인증서 저장소를 변경하지 않음 |
| Work 예약·PlayMCP 카카오 | 현재 세션에 도구 없음; 생성·발송하지 않음 |

Chromium에 부족한 환경 프록시 CA는 플랫폼이 제공한 공개 인증서이며 시스템 CA 저장소에서는 검증됐습니다.
사용자 Chromium 신뢰 저장소에 이를 영구 추가하려는 작업은 향후 TLS 신뢰 범위를 확대할 수 있어
자동 승인 심사에서 거절됐습니다. 사용자 명시 승인 없이 다른 경로나 간접 실행으로 우회하지 않습니다.
인증서·TLS 검증을 끄지 않았습니다. 브라우저 검증을 성공으로 기록하지 않습니다.

이 기록의 배포 검증은 위 커밋에 대한 관찰입니다. 이후 커밋의 배포 성공을 자동으로 뜻하지 않습니다.
위 TEST 수치는 가상 데이터이며 실제 시세 검증 결과가 아닙니다.
