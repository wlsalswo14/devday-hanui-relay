# Hanui 디자인 10종

`index.html`을 Chrome에서 열면 비교 갤러리가 표시된다. 각 HTML은 서버와 인터넷 없이 단독 실행되는 디자인 시안이다. 기능·계정·AI 대화·기록 저장은 없다. 모든 기록과 인용 위치는 화면 구성을 위한 샘플이다.

생성: `gemini-3.8-flash`, `thinkingLevel: HIGH`. 각 시안마다 독립 요청으로 HTML·CSS·SVG 구조를 생성했다. 기존 앱 CSS와 화면은 프롬프트에 전달하지 않았다. 검토·갤러리·반응형 보정은 Codex가 수행했다.

| 시안 | 구조 | 참고 |
|---|---|---|
| [Prism · 빛의 대화](01-prism.html) | 왼쪽 미니 레일 + 넓은 중앙 대화 캔버스 | [Mobbin](https://mobbin.com/) |
| [Clinic · 명료한 관리](02-clinic.html) | 상단 탭 + 지표 행 + 관리 대시보드 | [shadcn/ui Blocks](https://ui.shadcn.com/blocks) |
| [Folio · 나의 건강 저널](03-folio.html) | 책 목차 + 중앙 저널 + 여백 메모 | [Details.so Inspo](https://www.details.so/inspo) |
| [Night · 집중하는 에이전트](04-night.html) | 전체 화면 대화 + 상단 명령 바 + 하단 상태 띠 | [Prompt Motion](https://www.prompt-motion.com/) |
| [Grove · 일상의 회복](05-grove.html) | 식물 그래픽이 있는 왼쪽 면 + 오른쪽 체크인 | [Awwwards — Moxie](https://www.awwwards.com/sites/moxie) |
| [Swiss · 선명한 건강](06-swiss.html) | 큰 타이포 + 번호를 붙인 가로 정보 띠 | [Lapa Ninja Wellness](https://www.lapa.ninja/category/wellness/) |
| [Orbit · 하루를 설계하다](07-orbit.html) | 가로 주간 캘린더 + 시간축 + 오른쪽 대화 패널 | [shadcn/ui Blocks](https://ui.shadcn.com/blocks) |
| [Atlas · 근거를 읽는 공간](08-atlas.html) | 문헌 목록 / 원문 리더 / 풀이의 3열 작업대 | [Details.so Inspo](https://www.details.so/inspo) |
| [Bloom · 가벼운 습관](09-bloom.html) | 중앙 모바일 앱 구조 + 하단 내비게이션 | [Mobbin](https://mobbin.com/) |
| [Zen · 조용한 한의학](10-zen.html) | 오른쪽 세로 내비게이션 + 비대칭 원문·대화 | [Awwwards — Moxie](https://www.awwwards.com/sites/moxie) |

## 참고 조사

- [Prompt Motion](https://www.prompt-motion.com/): 타이포 중심 장면과 정돈된 제품 UI 프리뷰.
- [shadcn/ui Blocks](https://ui.shadcn.com/blocks): 상태별 대비, 명확한 구획, 컴포넌트의 일관된 간격.
- [Mobbin](https://mobbin.com/): 공개 홈페이지의 여백·아이콘 사용과 제품 화면 탐색 방식.
- [Lapa Ninja Wellness](https://www.lapa.ninja/category/wellness/): 웰니스·미니멀·타이포 분류의 공개 소개를 참고; 브라우저는 403.
- [Awwwards — Moxie](https://www.awwwards.com/sites/moxie): 의료 브랜드의 따뜻한 색감과 대담한 시각 위계.
- [Details.so Inspo](https://www.details.so/inspo): 세리프 제목, 넓은 여백, 요소별 탐색과 미세한 구획.

참고 사이트의 공개 화면과 설명만 조사했다. 로그인·유료 라이브러리는 열지 않았다. Prompt Motion의 외부 모델·프롬프트·스킬·코드는 사용하지 않았다. Lapa는 웹 도구로 공개 소개와 웰니스 분류를 확인했고, 로컬 브라우저 403 화면은 생성 모델에 전달하지 않았다. 참고 화면과 API 원본 응답은 `.runtime/`에만 보관하며 커밋하지 않는다.
