# 제출 후 변경

2026-10-09, 사용자가 해커톤 제출 후 Google 모델 사용을 별도로 요청했다.
제출 당시 OpenAI 구현·발표 자료·제출 ZIP은 소급 수정하지 않는다.

## 서비스 에이전트

- 기존: Codex CLI, GPT-6 Luna / high, 현재 ChatGPT 로그인.
- 현재: Gemini API, `gemma-4-26b-a4b-it` / minimal, 서버에서만 사용하는 API 키. high는 환경 변수로 선택한다.
- Windows 키 저장은 계정에 묶인 DPAPI 암호화이며 `.runtime/`은 Git 제외다.
- 키 하나를 실제 응답으로 확인하여 선택했다. 런타임에서 계정별 한도를 회피하는 키 순환은 하지 않는다.
- SQLite 전문 탐색, 정확한 원문 인용·문자 위치·한국어 해석, 환자 발언 근거와 일정 변경 검증은 유지한다.
- 실제 모델로 지침 기반 선제 질문, 환자 발언 2건 기록, 일정 생성·삭제를 검증했다. 테스트용 별도 DB에서 실행하여 사용자 기록은 변경하지 않았다.
- 공개 검색은 Google Search 검색 메타데이터와 출처를 확인한 결과만 허용한다. 병원에 실제 예약을 보내는 기능은 없다.
- 검색과 구조화는 별도 호출로 나눠 원문 출처가 없는 기억 기반 답변을 차단한다.
- 웹검색 실호출은 출처 메타데이터 미반환과 응답 대기 실패가 관측되어 아직 정상 동작 검증을 마치지 못했다. 결과를 꾸며 표시하지 않고 오류를 반환한다. 출처 검증·오류 처리의 자동 테스트는 통과했다.
- Cloudflare 터널과 공개 데모 프로세스는 사용자 요청으로 종료했다. 로컬 `http://127.0.0.1:8765`만 유지한다.

## 응답 지연·인용 출력 보완

Gemma `high` 실제 브라우저 질문은 약 80초가 걸렸다. 기본 사고 모드를 `minimal`로 바꾸고 DB 전체 검색 후 상위 4건의 관련 원문 구간을 전달한다. `HANUI_GEMMA_THINKING=high`로 이전 사고 모드를 선택할 수 있다. 원문 전체는 DB에 보존된다.

빠른 모드의 한자 표기 변경으로 인용 검증에 실패하는 문제를 막기 위해, 에이전트가 DB의 정확한 원문 후보 ID를 선택하고 한국어 해석을 작성하도록 했다. 서버가 해당 원문을 그대로 가져와 전체 본문과 대조하고 문자 위치를 계산한다. 없는 후보는 차단한다. 실제 브라우저 질문에서 약 9초에 답변·원문·해석 출력과 검증을 확인했다. 단일 질문의 측정이며 응답 시간 보장은 아니다.

질문은 전송 즉시 화면에 임시로 표시하고 대기 시간도 표시한다. 취소·실패 시 임시 표시를 제거하며 저장하지 않는다. Google 5xx만 같은 키로 한 번 재시도하며 429는 재시도하거나 다른 키로 우회하지 않는다.

## 디자인 재시도

원래 디자인 체크포인트: `design-checkpoint-before-gemini-redesign-20261009`.
디자인 생성 모델은 사용자가 지정한 `gemini-3.8-flash`, thinking level `high`다.
2026-10-10 재시도에서 CSS 생성에 성공했다. 첫 응답은 출력 한도로 잘렸으나 완전한 규칙까지 보존하고, 같은 모델의 high 설정으로 후반부를 이어 생성했다. Google API를 사용했으며 Antigravity CLI로 생성하지 않았다.

생성된 시각 스타일을 전체 화면에 적용했다. 220px 왼쪽 메뉴, 아이보리·짙은 초록 색상, 넓은 대화 영역, 구분된 기록·자료·캘린더·리포트와 모바일 패널을 구성한다. 기존 CSS는 모델이 놓친 동적 요소와 인쇄의 기능 기반으로 남겼다. Codex가 실제 JS 선택자와 다른 CSS 이름을 수정하고, 메시지 입력창이 화면 안에 머물도록 크기를 보완했다. 모바일 실천율 표는 지침 이름을 유지하며 표 안에서 가로로 스크롤한다. 기존 A4 인쇄 규칙은 그대로 보존했다.

검증: 320·360·390·768·1024·1440px의 24개 화면에서 글자 대비, 16px 답변·원문, 가로 넘침, 자료 창과 사이드바를 검사했다. 생활기록·예약·캘린더·ICS, 여러 대화, 환자 발언 근거 및 1페이지 A4 리포트도 합성 데이터로 검증했다. 브라우저 콘솔 오류는 없었다. 테스트는 별도 DB를 사용하여 사용자 기록을 변경하지 않았다.

## 기존 스타일을 전달하지 않은 오리지널 디자인

2026-10-10 사용자가 Gemini 감성의 독창적인 디자인을 다시 요청했다. 직전 디자인은 `design-checkpoint-before-original-gemini-20261010` 태그로 보존했다.

`gemini-3.8-flash` / high에 기능용 HTML과 실제 동적 CSS 클래스 목록만 전달했다. 기존 CSS·스크린샷·색상·메뉴 폭을 디자인 참고로 전달하지 않았다. 산뜻한 블루·보라·코랄, 넓은 대화 캔버스, 상단 메뉴, 부드러운 입력창을 갖춘 독립적인 CSS를 생성했고 기존 화면 스타일을 교체했다. 응답의 CSS 규칙은 완전했지만 JSON 문자열의 마지막 따옴표가 누락되어 그 형식만 복구했다.

Codex 검토에서는 작은 화면의 넘침, 입력창 고정, 실제 동적 요소, 캘린더 선택 상태·모바일 건수, 코랄 색의 글자 대비를 보완했다. 화면에 이전 시각 CSS를 기반으로 남기지 않았다. 기존 인쇄용 CSS는 `report-print.css`로 분리하고 `media="print"`로만 적용하여 A4 출력 형식을 보존했다.

검증: 여섯 화면 폭의 24개 화면, 생활기록·예약·캘린더·ICS·여러 대화·자료 창, 합성 시연의 환자 근거와 1페이지 A4 출력이 통과했다. 글자 대비와 모바일 표의 지침 이름, 넓은 대화 영역 및 화면 안의 입력창을 확인했다. 콘솔 오류는 없었다.

## 대화 중심의 최소 UI

반복 제목·모드 안내·사용자 이름·글자 수·전송 방법·상시 설명을 기본 화면에서 덜어냈다. 메뉴는 대화·기록·자료·일정·리포트로 줄이고 새 대화·자료 패널은 이름을 가진 아이콘 버튼으로 제공한다. 이름 변경·삭제·모드 선택은 키보드로도 열 수 있는 ⋯ 메뉴로 옮겼다. 빈 대화에는 한 문장과 입력창만 표시한다.

원문·위치·한국어 해석은 삭제하거나 자르지 않고, 각 답변의 ‘근거’ 펼침에 보존한다. 환자 발언 근거도 확인할 수 있다. 저장된 대화 내용은 변경하지 않는다. 실제 Gemma 응답 지침은 기본 1~2문장·120자 미만으로 조정하되 사용자가 상세 답변을 요청하거나 안전상 필요한 경우 더 설명하도록 한다. 새 기본 응답 길이는 프롬프트 지침이며 강제 자르기를 하지 않는다.

화면·기록·예약·캘린더·인쇄 검증과 93개 자동 테스트가 통과했다. ⋯ 메뉴의 삭제·이름 변경, 접힌 인용의 해석·원문 조회도 확인했다. 직전 화면은 `design-checkpoint-before-chat-minimal-20261010` 태그로 보존했다.

## Gemini 웹 구조의 사이드바

사용자 요청으로 `gemini-3.8-flash` / high API에 Gemini 웹 형태의 구조를 생성하도록 했다. 모델이 만든 `shell.css`를 기능 스타일 위에 적용했다. 왼쪽 사이드바에 새 대화, 기능 메뉴, 개별 대화 목록, 생활기록·자료 펼침, 설정을 모았다. 상단 탭·대화 선택 바·오른쪽 자료 패널은 없애고, 주 영역은 대화와 화면 하단 입력창에 집중한다.

사이드바는 데스크톱에서 260px이며 68px으로 접을 수 있다. 모바일은 처음 닫힌 메뉴를 버튼으로 열고, 기능 선택·새 대화·대화 전환 후 닫는다. 닫힌 모바일 메뉴는 `inert`로 비활성화한다. Tab 이동 범위, Esc 닫기와 포커스 복귀, 배경 닫기를 구현했다. 기존 대화·기록·일정 데이터를 옮기거나 변경하지 않는다. 자료는 오른쪽 대신 왼쪽 사이드바 안에서 펼쳐 확인한다.

검증: 여섯 화면 폭의 24개 화면에서 대비·원문·해석·넘침을 확인했다. 사이드바 접기와 재접속 유지, 개별 대화 전환, 모바일 전체 메뉴·설정 위치·포커스·입력창을 확인했다. 생활기록·병원·예약·캘린더·ICS·A4 1페이지와 7가지 응답 취소 경로도 통과했다. 브라우저 오류는 없었다. 직전 화면은 `design-checkpoint-before-gemini-sidebar-20261010` 태그로 보존했다.
# 2026-10-10: Background Playwright search

The Gemma service decides whether a question needs live search as part of its DB retrieval
planning call. Only a true search_needed decision for the current question triggers the separate
headless Playwright MCP, using the model's public search query rather than
patient history or clinician plans. Browser result snippets are untrusted model context;
classical DB quotations retain the existing exact-original validation. Observed external
links are saved as conversation search sources. No extension token is required by this path,
and it does not control the user's Chrome tabs. `start.ps1` starts the headless MCP process.

Live headless testing encountered Google's HTTP 429/CAPTCHA page. This is a documented
limitation, not a successful search. The app displays the failure and answers from the DB;
it never fabricates search evidence or automatically bypasses the challenge. The earlier
extension-based manual search returned real links, but that does not establish headless
search success. Browser task routing supports explicit browser instructions separately,
with current snapshot references and no arbitrary JavaScript, shell, filesystem or credential
tools. Cancellation is checked before and after MCP actions; an in-flight browser HTTP call
has a 25-second timeout. Cancelled replies are not saved.

