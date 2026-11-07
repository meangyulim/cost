# 카카오 알림 GitHub Actions 발송

2026.11 변경: 루틴의 카카오 PlayMCP 커넥터가 재연결 후에도 24시간 안에 끊겨 11/2 이후 알림이 전부 실패했다.
이제 루틴은 카카오 도구를 호출하지 않고 `dispatch/<회차 ID>.json`에 `queued` 기록만 올린다.
`Send Kakao notifications` 워크플로(`.github/workflows/kakao-notify.yml`)가 카카오 REST API로 '나에게 보내기'를 한 번 실행한다.

## 흐름

1. 루틴이 보고서 배포 성공을 확인한 뒤 아래 형식의 `queued` 기록을 `main`에 일반 push한다.
2. `dispatch/*.json` push가 `kakao-notify.yml`을 실행한다. 수동 실행(workflow_dispatch)도 할 수 있다. 동시 실행은 `kakao-notify` 그룹으로 하나씩 처리한다.
3. `scripts/kakao_notify.py send`는 `git pull --rebase` 후 `status == "queued"`인 기록만 처리한다.
4. 검사
   - 파일 이름과 `report_id`가 같아야 한다.
   - `report_url`이 `https://meangyulim.github.io/cost/reports/{report_id}/`와 정확히 같아야 한다.
   - `kakao_summary`가 있어야 한다.
   - `send_tool_called`, `attempted_record_created`가 `false`여야 한다.
   - `queued_at_utc`가 6시간을 넘으면 `status: "expired"`로 바꾸고 보내지 않는다.
   - 그 밖의 검사 실패는 `status: "failed"`와 `failure_reason`을 남기고 보내지 않는다.
5. 보내기 전에 `status: "attempted"`, `attempted_at_kst/utc`, `attempted_record_created: true`, `workflow_run_id`를 커밋·push한다.
   push가 실패하면 rebase 후 최대 3회 다시 시도한다. 그래도 실패하거나 원격에서 다시 읽은 기록이 다르면 보내지 않는다.
6. `KAKAO_REFRESH_TOKEN`으로 access token을 갱신한다. 응답에 새 refresh token이 있으면 `gh secret set KAKAO_REFRESH_TOKEN`(값은 stdin)으로 교체한다. 교체가 실패해도 이번 전송은 하고 작업은 실패로 끝낸다.
7. 요약 + 줄바꿈 + 회차 URL을 200자 이하로 만든다. URL은 자르지 않고 요약을 자른다(`…`). 버튼은 `브리핑 열기`.
8. 전송은 한 번만 하고 재시도하지 않는다. 결과를 기록해 push한다.
   - `sent`: `result_code == 0`
   - `failed`: HTTP 오류, `result_code`가 0이 아님, 토큰 갱신 실패(`token_*`, 이 경우 전송 호출 없음)
   - `unknown`: 전송 호출 뒤 네트워크 오류 또는 판독 불가 응답
   - HTTP 상태와 오류 코드만 남긴다. 토큰·인가 코드·응답 원문은 출력·저장하지 않고, 토큰은 `::add-mask::`로 가린다.
   - 결과 push 실패는 재전송 이유가 아니다.

`attempted`·`sent`·`failed`·`unknown`·`expired` 기록은 다시 보내지 않는다. 같은 회차를 다시 보내려면 새 회차 ID가 필요하다.

## queued 기록 형식

```json
{
  "report_id": "us-close-2026-11-06",
  "status": "queued",
  "queued_at_kst": "2026-11-07T06:40:00+09:00",
  "queued_at_utc": "2026-11-06T21:40:00Z",
  "report_url": "https://meangyulim.github.io/cost/reports/us-close-2026-11-06/",
  "deployment_commit": "배포 성공을 확인한 커밋 SHA",
  "deployment_run_id": 42295432611,
  "deployment_conclusion": "success",
  "kakao_summary": "URL을 뺀 핵심 요약, 150자 이하",
  "send_tool_called": false,
  "attempted_record_created": false,
  "retry_count": 0
}
```

- 시각은 실제 시계로 확인한 값을 쓴다. `queued_at_utc`는 시간대 표기(`Z` 또는 `+00:00`)가 있어야 한다.
- `kakao_summary`는 URL 없이 150자 이하로 쓴다. 발송 시 URL과 합쳐 200자를 넘으면 요약 끝을 자른다.
- 이미 dispatch 파일이 있는 회차는 새로 queued로 만들지 않는다.

## Secrets

| 이름 | 내용 | 등록 |
| --- | --- | --- |
| `KAKAO_REST_API_KEY` | 카카오 개발자 앱의 REST API 키 | 직접 등록 |
| `KAKAO_CLIENT_SECRET` | 앱에서 Client Secret을 켰을 때만 그 값. 끄면 비워 둔다 | 직접 등록(선택) |
| `GH_SECRET_TOKEN` | 이 저장소만 대상으로 `Secrets: Read and write` 권한을 준 fine-grained PAT | 직접 등록 |
| `KAKAO_REFRESH_TOKEN` | 카카오 refresh token | `kakao-setup` 워크플로가 자동 저장·갱신 |

저장소 Settings → Secrets and variables → Actions → New repository secret에서 등록한다. 값은 코드·요청 파일·대화에 넣지 않는다.

## 최초 설정

1. [카카오 개발자](https://developers.kakao.com) 앱에서 카카오 로그인을 켜고 Redirect URI에 `https://meangyulim.github.io/cost/`를 등록한다. 동의항목에서 `카카오톡 메시지 전송(talk_message)`을 켠다.
2. 위 Secrets 표의 직접 등록 항목을 넣는다.
3. 브라우저에서 아래 주소를 연다(`{REST_API_KEY}`를 실제 키로 바꾼다).
   ```
   https://kauth.kakao.com/oauth/authorize?client_id={REST_API_KEY}&redirect_uri=https://meangyulim.github.io/cost/&response_type=code&scope=talk_message
   ```
4. 로그인·동의 후 이동한 주소 `https://meangyulim.github.io/cost/?code=...`에서 `code=` 뒤 값을 복사한다. 이 코드는 1회용이며 곧 만료되므로 바로 다음 단계를 실행한다.
5. Actions → `Set up Kakao notifications` → Run workflow에서 `code`에 값을 넣고 실행한다. `send_test`가 켜져 있으면 "카카오 알림 연결 테스트입니다." 메시지가 한 번 온다.
6. 실행이 성공하고 테스트 메시지를 받았을 때만 연결 완료로 본다. refresh token이 만료되거나 앱 동의가 철회되면 3~5단계를 다시 한다.
