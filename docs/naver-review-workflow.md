# 네이버 후기 갱신

## 검증한 수집 경로 (2026-09-16)

ChatGPT의 사용자 전용 브라우저에서 네이버 스마트스토어센터에 로그인한 뒤
백년화편 → 문의/리뷰관리 → 리뷰 관리에서 기간을 선택하고 검색 → 엑셀다운.
판매자센터 URL: https://sell.smartstore.naver.com/#/review/search

이 방식은 회사 PC 수집기를 거치지 않는다. 네이버 로그인과 판매자센터의
2단계 인증은 필요하다. 로그인 세션은 영구적이지 않으며 재인증 시 사용자가
보안 입력창에서 인증한다. 비밀번호·인증번호·쿠키를 코드나 저장소에 저장하지 않는다.
이 절차 자체가 매일 자동 실행되는 것은 아니다.

최근 6개월(2026-03-17~2026-09-16) 조회에서 11,340건의 엑셀 내보내기를 확인했다.
화면 조회 건수와 실제 엑셀 행 수를 대조하고, 누락 기간 전체를 포함했는지 확인한다.
기간이 조회 상한을 넘으면 기간을 나누고 겹치는 기간도 함께 병합한다.

## 대시보드 반영

대시보드 → 수집 로그 → 네이버 후기 병합에서 판매자센터 XLSX 또는 정규화한 JSON을 선택한다.
기존 후기는 삭제하지 않는다. 같은 리뷰글번호를 우선 매칭하며,
리뷰글번호가 없는 과거 자료와는 `(author, date, content[:100])`으로 매칭한다.
기존 정책대로 상품명은 중복 키에 포함하지 않는다.
기존 데이터가 없는 파일에서는 동일한 작성자·날짜·본문 앞 100자인 리뷰가 하나로 합쳐질 수 있다.

파일의 실제 셀 범위를 사용한다. 네이버 XLSX는 선언된 시트 범위가 A1뿐인 경우가 있다.
Python openpyxl로 읽을 경우 read_only 모드에서 `worksheet.reset_dimensions()`가 필요하다.
SheetJS에서는 `nodim: true`로 처리한다.

필수 매핑:

| 판매자센터 열 | JSON |
| --- | --- |
| 리뷰등록일 | date (YYYY-MM-DD) |
| 구매자평점 | score (숫자 1~5) |
| 상품명 | product |
| 리뷰상세내용 | content (전문) |
| 등록자 | author (네이버가 제공한 마스킹 상태) |
| 리뷰글번호 | review_no (문자열) |
| 리뷰구분 | review_type |

`platform`은 `naver`, `title`은 빈 문자열이다. 주문번호 등 분석에 불필요한 열은 전송하지 않는다.
원본 파일·정규화한 실제 후기·백업은 GitHub에 커밋하지 않는다.

AI가 정규화한 JSON을 직접 업로드할 때:

```bash
python scripts/import_smartstore.py /absolute/path/reviews.json
python scripts/import_smartstore.py /absolute/path/reviews.json --apply
```

첫 명령은 읽기와 검증만 한다. 두 번째는 업로드별 ID로 청크를 전송하고
전체 건수 확인 후 병합한다. 중간 실패 시 새로운 업로드 ID로 처음부터 재실행한다.
완료 시 추가·갱신·기존·최종 건수를 확인한다. `/api/smartstore-status`의
`last_import`, `last_review_date`와 대시보드 후기 목록까지 대조한다.

## 운영 데이터 보호

- 빈 파일, 유효하지 않은 날짜·평점·본문은 거절한다.
- 기본 동작은 병합이며 이전 PC 프로그램도 같은 API 경로를 사용할 수 있다.
- 기존 `replace: true`는 해당 업로드의 임시 청크를 초기화하는 의미다. 본 데이터 삭제가 아니다.
- 기존 파일 읽기에 실패하면 중단한다. 실패를 빈 데이터로 처리하지 않는다.
- 변경 전 원본은 Railway 영구 볼륨의 `data/smartstore_backups/`에 백업한다.
- 전송 완료 전에는 실제 후기 파일을 바꾸지 않는다.
- 후기 업로드는 로그인 성공의 증거가 아니다. 인증 상태와 후기 최신성은 구별한다.

공식 커머스API는 현재 리뷰 조회 기능을 제공하지 않는다:
https://github.com/commerce-api-naver/commerce-api/discussions/3309

## GPT 없이 자정 자동 실행

`naver_automation.py`는 Playwright로 판매자센터의 최근 6개월 리뷰 엑셀을 내려받아
기존 병합 함수에 전달한다. LLM이나 OpenAI API 호출은 없다.
`naver_daily` 작업은 Asia/Seoul 00:00, 동시 실행 1개, 지연 허용 1시간으로 등록된다.
서버 재시작 때 당일 성공 이력이 없으면 로그인 상태가 설정된 경우 1회 보충 실행한다.
서버는 단일 replica/uvicorn worker로 운영한다. 브라우저 메모리·서버 비용은 별도다.

최초 연결은 `scripts/connect_naver.py`를 사용자의 PC에서 실행하여 공식 네이버 창에
직접 로그인한다. 전용 connection.json에는 1회용 연결 코드만 들어가며 로그인 비밀번호는
들어가지 않는다. 연결 코드는 서버 환경의 SHA256 값과 비교하며 48시간 후 만료된다.
실제 서버에서 엑셀 수집·병합이 성공해야 연결 코드를 소진하고 준비 완료로 표시한다.
클라이언트 PC의 로그인 세션을 서버에서 받아주지 않는 경우 연결은 실패로 표시되며,
클라우드 IP 차단·추가 인증을 우회하지 않는다. 이 경우 서버 직접 인증 수단 또는 PC 실행으로
추가 구성이 필요하다. 로그인 상태를 받았다는 사실만으로 자동 갱신 성공을 주장하지 않는다.

세션은 `/app/data/naver_private/state.json`에 0600으로 보관하며 공개 저장소와 정적 경로에
포함하지 않는다. 공개 상태 API는 세션·연결 코드를 반환하지 않는다.
비밀번호·OTP는 저장/수집하지 않는다. 엑셀 임시 파일은 처리 후 삭제한다.
인증 만료나 화면 변경 시 기존 후기는 보존되고 대시보드에 오류가 표시된다.
상태 확인: `/api/smartstore-status`의 `automation` (state, next_run, last_success).

연결 패키지 생성 시 NAVER_PAIRING_SHA256 및 NAVER_PAIRING_EXPIRES를 서버에 설정한다.
연결 코드 원문이나 실제 후기 데이터는 GitHub에 커밋하지 않는다.

Playwright 공식 참고: https://playwright.dev/python/docs/auth 및
https://playwright.dev/python/docs/downloads
