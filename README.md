# Hanui Relay

한의학 자료를 찾아보고, 개인 생활기록을 기억하며 대화하는 로컬 데모.

## 지금 구현된 기능

- 지속 대화와 재접속 후 대화 복원.
- 사용자 발언을 근거로 수면·식사·활동·스트레스·생활 목표 기록.
- 실제 출처가 있는 소량의 한의학 자료를 SQLite에서 검색.
- 답변에 사용한 자료의 원문 링크·요약·근거 수준·적용 한계 확인.
- 현재 ChatGPT 계정으로 **GPT-6 Luna / high** 호출.
- 모델을 호출하지 않는 별도의 샘플 모드.
- 현재 대화와 연결된 생활기록의 전체 삭제.

병원 후기 검색·예약·캘린더·약재 구매는 아직 연결하지 않았다. 미병·질병·체질의 개인 진단과 증상에 맞춘 약재·복용량 추천을 수행하지 않는다.

## 실행

Python 3.11 이상. 앱 서버와 DB는 Python 표준 라이브러리만 사용한다.

```powershell
python server.py --port 8765
```

브라우저에서 <http://127.0.0.1:8765>를 연다. 서버는 loopback에만 바인딩하며 공유·공개 배포용 인증은 포함하지 않는다.

AI 대화에는 공식 Codex CLI와 기존 ChatGPT 로그인이 필요하다.

```powershell
codex login status
```

`HANUI_CODEX_EXECUTABLE`로 공식 Codex 실행 파일의 경로를 지정할 수 있다. API 키를 읽거나 복사하지 않는다. 실행마다 요청 모델은 `gpt-6-luna`, reasoning effort는 `high`이며 다른 모델·타사 AI로 자동 전환하지 않는다. 계정에서 모델에 접근할 수 없거나 사용량 한계에 도달하면 오류를 표시한다.

AI 호출은 `codex exec --ignore-user-config --ephemeral`을 사용해 기존 인증만 재사용한다. 대화의 최근 맥락·사용자 생활기록·검색된 자료를 텍스트로 전달하며 모델의 셸·앱·플러그인·브라우저 등의 기능을 비활성화한다. 모델의 작업 디렉터리는 비어 있는 `.runtime/model-workspace`다. 서비스가 한의학 DB 검색과 생활기록 저장을 담당하고, 모델이 로컬 파일을 직접 탐색하지 않는다.

사용자는 첫 AI 대화 전에 정보 전달을 확인한다. 모델 출력은 JSON 형식·허용된 출처 ID·사용자 원문 인용을 검증한다. 이 검사는 의학적 정확성이나 요약 전체의 의미 일치를 보장하는 임상 검증을 뜻하지 않는다.

## 자료와 개인 기록

`data/knowledge.seed.json`은 공개 출처에서 확인한 짧은 자체 요약 7건이다. 미병 관련 개념/연구 소개, 생활관리 지침의 범위, 감초·황기·반하의 기원 정보, 공식 정보 포털 안내를 포함한다. 전체 한의학 DB나 증상별 치료 추천 데이터셋은 아니다.

다운로드한 공개 PDF는 `data/source-documents/`에 로컬 참조용으로 보관하며 Git에서 제외한다. 공개 열람을 재배포 허가로 해석하지 않는다. 공개 가능한 출처·다운로드 검증 정보는 `data/sources.manifest.json`에 기록했다. seed에서 원문으로 이동해 적용 대상과 한계를 확인할 수 있다.

대화·생활기록 DB와 임시 모델 파일은 `.runtime/`에 저장되고 Git에서 제외된다. 사용자는 대화·기록 삭제로 해당 세션의 메시지와 생활기록을 삭제할 수 있다. 첫 MVP의 기억은 사용자 자기보고이며 진단 결과가 아니다. 사용자가 기록을 정정한 경우 이전 발언과 새 발언이 모두 남는다.

## 검증

```powershell
python -m unittest discover -s tests -v
```

실제 계정 사용량을 소비하는 합성 대화 2회 검증:

```powershell
python live_smoke.py
```

샘플/자동 테스트는 모델의 의료 성능 평가가 아니다. 별도 실행 결과는 `.runtime/live-check.json`에 보관한다.

## 행사 저장소

저장소: <https://github.com/wlsalswo14/devday-hanui-relay>

제출 플랫폼의 실제 안내에 맞춰 GitHub 주소와 최종 심사 대상 커밋 SHA를 제출한다. 현재 커밋 SHA는 `git rev-parse HEAD`로 확인할 수 있다. 제출할 때는 해당 커밋과 같은 버전의 데모, 접근 권한, 제출 마감과 요구 항목을 확인한다.

기획·자료와 구현의 구분은 [개발 기록](docs/DEVELOPMENT.md), 확인한 동작과 한계는 [검증 기록](docs/VALIDATION.md)에 정리했다.

## 공식 연동 참고

- Codex 비대화형 실행: <https://learn.chatgpt.com/docs/noninteractive>
- Codex app server 및 계정/모델 조회: <https://learn.chatgpt.com/docs/app-server>
