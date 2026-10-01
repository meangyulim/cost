# 미국 일별 분석 입력

2026.10.01 사용자가 Massive API 키를 제공했다. SPY/QQQ/IWM/SOXX/NVDA의
85거래일 자료와 전체 일별 12,613개 증권, 종목 뉴스의 조회가 성공했다.
AAPL 스냅샷과 I:SPX 직접 조회는 403이므로 장중 실시간 또는 지수 사용 권한으로 취급하지 않는다.
사용자는 개인 요금제의 공개 게시 제한을 안내받은 뒤 연결·활용을 지시했다.
이 사용자 지시는 Massive의 라이선스 허가를 얻었다는 증거가 아니다.

## 키 설정과 실행

GitHub 저장소 Settings → Secrets and variables → Actions에서
`MASSIVE_API_KEY`를 Repository secret으로 등록한다. 공개 Variables·코드·요청 파일에 키를 넣지 않는다.
현재 연결된 GitHub 도구에는 secret 등록 API가 없어 최초 등록은 사용자가 해야 한다.
`KRX_API_KEY`와 다른 키다. 채팅에 있는 값을 이후 예약이 읽는다고 가정하지 않는다.

`Collect US briefing inputs` 워크플로를 수동 실행하거나 `data/us-request.json`을 갱신한다.
다음 요청 형식에는 비밀값이 없다. `requested_at`은 매번 실제 KST 시각으로 변경해 새 요청 커밋을 만든다.

```json
{"end_date": "2026-09-30", "watch": ["NVDA", "AAPL", "MSFT"], "requested_at": "실제 날짜 포함 KST 시각"}
```

장전은 공식 달력에서 확인한 이전 거래일, 장후는 해당 뉴욕 거래일을 요청한다.
빈 날짜는 뉴욕 어제다. 아직 허용되지 않은 날짜만 최근 허용 자료로 이동할 수 있다.
반드시 반환된 `data_date`를 확인하며 이전 날짜를 당일 종가로 표기하지 않는다.
스케줄·cron·추가 예약은 생성하지 않는다.

해당 요청 커밋의 workflow 성공과 `us-analysis-<run ID>` artifact의 analysis.json을 확인한다.
산출물 보존은 3일이다. 공개 저장소 artifact는 비밀 보관함이 아니다.
키와 원시 전체 증권 목록은 저장하지 않는다. 산출물에는 계산에 필요한 소수 가격과 파생 지표만 포함된다.
Secrets 등록과 GitHub 수집 성공을 실제 확인하기 전에는 자동 연결 완료라고 표현하지 않는다.
키 미설정·기간 권한·네트워크 실패 시 미국 브리핑은 기존 원문 조사로 계속 작성한다.
확인하지 못한 Massive 분석 수치를 임의로 채우지 않는다.

## 수집과 계산

- `scripts/massive_analysis.py`는 `MASSIVE_API_KEY`를 환경변수로 읽어 HTTPS Authorization 헤더에만 전달한다.
  리다이렉트는 거절하며 TLS 검증을 유지한다. 응답 오류·원시 자료·키는 로그에 출력하지 않는다.
- 요청 시작 간격 13초로 무료 요금제의 분당 5회 한도 안에서 순차 수집한다.
  429와 일시적 네트워크/서버 실패는 최대 3회로 제한해 재시도하고 인증 오류는 즉시 중단한다.
- SPY/QQQ/DIA/IWM과 SOXX/11개 업종 ETF, 지정한 관찰 종목의 최근 65거래일을 비교한다.
  모든 시계열의 날짜를 SPY와 대조하고 누락·중복·비유한 수치·잘린 응답은 거절한다.
- 5·20거래일 가격수익률, 20·60일 이동평균, 직전 5거래일 평균 대비 거래량,
  SPY 대비 업종 ETF의 20거래일 상대 수익률을 계산한다.
- 전체 증권 시장 폭은 최신일/이전일 모두 거래가 있고 유효 가격이 있는 동일 티커를 비교한다.
  OTC는 제외하지만 ETF·우선주·워런트 등은 포함하므로 보통주 시장 폭이나 S&P500 구성종목의 상승 비율로 쓰지 않는다.
- 관찰 종목의 표시용 정규장 종가는 `/v1/open-close`로 해당일·이전일을 별도 조회한다.
  일별 aggregate의 시각을 정규장 폐장 시각으로 쓰지 않는다. 폐장 시각은 공식 달력에서 확인한다.
  정규장 요약의 preMarket/afterHours를 현재 장전 실시간 가격으로 쓰지 않는다.
- 분할 보정 가격수익률이며 배당 재투자 총수익률은 아니다. 거래량은 순매수/기관 수급이 아니다.
  `forecast_probability: null`, `backtest_status: not_validated`를 유지한다.
- 뉴스·일정·환율·실제 지수 값은 기존 공식/원문 조사로 보완한다. ETF 가격을 지수 포인트로 바꾸지 않는다.

## 보고서 표시

2026.10.01 사용자는 Massive 제공업체 정보를 독자 화면에 표시하지 않도록 지시했다.
해당 source 항목에만 `show_public: false`를 적용한다. 빌더는 이 항목을 하단 출처 목록에서 생략한다.
뉴스·공시·달력 등 다른 출처는 기존대로 표시한다. 실제 제공업체·조회 범위는 원본 source 기록에 유지하며
다른 제공업체의 자료처럼 기록하지 않는다. 이 표시 옵션은 라이선스 제한을 해소하지 않는다.
기준일·거래 구간·ETF 대용치·자료 지연 등 투자 판단에 필요한 정보는 독자 화면에 계속 표시한다.
이 작업은 과거 회차를 수정하거나 출처를 지우지 않는다.

공식 명세: https://massive.com/docs/rest/stocks/aggregates/custom-bars,
https://massive.com/docs/rest/stocks/aggregates/daily-market-summary,
https://massive.com/docs/rest/stocks/aggregates/daily-ticker-summary.
공개 게시 제한: https://massive.com/legal/market-data-terms-of-service,
https://massive.com/knowledge-base/article/which-plan-do-i-need-to-show-massive-data-in-my-app.
