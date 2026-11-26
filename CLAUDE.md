# CLAUDE.md

이 파일은 Claude Code(claude.ai/code)가 이 저장소에서 작업할 때 참고하는 안내서이다.

## 프로젝트

ClaudePython: AI를 이용한 파이썬 코드(강사용). 강의용 Python 예제 코드를 Claude와 함께 작성하는 저장소이다.

현재 과제: OEM-SWR-001(전자식 차일드락 제어 SW, ASIL B 안전 요구 포함)을 Python PC/SIL 참조 구현과 Web 시뮬레이터로 개발한다.
- 진행 계획과 프로젝트 결정 사항(D-01~D-06)은 `docs/00_plan/개발계획서.md`에 있다.
- 입력 문서는 `OEM/`에 있다. 교육 과정 밖 배포가 금지된 문서라 `.gitignore`로 제외하고, GitHub 저장소는 비공개로 운영한다.

## 개발 환경

- **언어:** Python 3.12로 고정한다. OEM 요구사항이 실행 환경을 Python 3.12 PC/SIL로 지정했기 때문이다(`requires-python = ">=3.12,<3.13"`).
- **의존성:**
  - 런타임 의존성은 없고, 표준 라이브러리만 쓴다. Web 시뮬레이터도 `http.server`로 만든다.
  - 개발 도구는 `requirements-dev.txt`에 버전을 고정해 둔다. 설치: `python -m pip install -r requirements-dev.txt`
- **단위 테스트:** pytest를 쓰고, 브랜치 커버리지는 pytest-cov로 측정한다. 측정 대상(`src`, `tools`)은 `pyproject.toml`에 설정돼 있다.
  - 전체 실행: `python -m pytest --cov --cov-branch --cov-report=term-missing --cov-fail-under=100`
  - 개별 실행: `python -m pytest tests/path/test_x.py::test_name`
- **정적 분석:** Ruff와 mypy를 쓴다. 설정은 `pyproject.toml`의 `[tool.ruff]`, `[tool.mypy]`에 있다. 규칙의 근거는 `docs/03_swe3_detailed_design/정적분석계획.md`(SAP-ECL-001)이다.
  - Ruff: 줄 길이 80, C901 복잡도 10. `time`, `random`, `threading`, `os` 등은 banned-api로 금지돼 있다.
  - mypy: strict, 명시적 Any 금지
  - 검사: `python -m ruff check .`
  - 포맷 확인: `python -m ruff format --check .`
  - 타입 검사: `python -m mypy`
- **함수 길이·주석률:** `python -m tools.check_metrics src tools`로 측정한다. 위반이 있으면 종료 코드가 1이다.
- **디렉터리:**

  | 경로 | 내용 |
  |---|---|
  | `src/childlock/` | 제품 소스 |
  | `tools/` | 개발 도구 (품질 기준 적용 대상) |
  | `tests/` | 테스트. `src/`, `tools/`와 같은 구조로 둔다 |
  | `docs/` | 단계별 산출물 (`00_plan`, `01_swe1_requirements` …) |

## 개발 절차

- 개발은 아래 순서로 진행하고, 단계를 건너뛰지 않는다. 각 단계는 A-SPICE 프로세스에 대응한다.

  | 순서 | 단계 | A-SPICE | 사용할 도구 |
  |---|---|---|---|
  | 1 | 요구사항 분석 | SWE.1 | |
  | 2 | 아키텍처 설계 | SWE.2 | |
  | 3 | 상세 설계 | SWE.3 | |
  | 4 | 구현 | SWE.3 | `test-driven-development` 스킬 |
  | 5 | 단위 테스트 | SWE.4 | pytest, pytest-cov, Ruff |
  | 6 | 통합 테스트 | SWE.5 | pytest |
  | 7 | 시스템 테스트 | SWE.6 | `sw-system-test-case` 스킬 / `system-test-case-generator` 서브에이전트 |

- 단계마다 산출물을 남기고, 앞 단계 산출물과 양방향 추적성을 유지한다. 예: 요구사항 ID ↔ 설계 요소 ↔ 테스트 케이스.
- **구현은 TDD로 한다.** 구현 코드를 쓰기 전에 반드시 `test-driven-development` 스킬을 불러와 Red-Green-Refactor 순서를 따른다.
  - 순서: 실패하는 테스트 작성 → 실행해서 예상한 이유로 실패하는지 확인 → 최소한의 코드 작성 → 전체 테스트 실행
  - 새 기능, 버그 수정, 리팩터링, 동작 변경 모두 해당한다. `.claude/skills/*/scripts/` 아래 스킬 스크립트도 포함한다.
- 스킬이 허용하는 예외(일회성 프로토타입, 생성 코드, 설정 파일)에 해당해도 사용자에게 먼저 묻는다.
- `test-driven-development` 스킬은 https://github.com/obra/superpowers (MIT, 커밋 22f0b46)에서 `.claude/skills/test-driven-development/`로 가져왔다. 갱신할 때는 원본의 `skills/test-driven-development/`를 다시 복사한다.

## 소스코드 품질

아래 기준은 모두 PR 병합 조건이다. 하나라도 만족하지 못하면 작업을 끝난 것으로 보고하지 않는다.

| 항목 | 기준 | 측정 방법 |
|---|---|---|
| 브랜치 커버리지 | **반드시** 100% | `pytest --cov-branch --cov-fail-under=100` |
| 테스트 성공률 | 100% (실패·에러 0건) | pytest 결과. 건너뛴 테스트(skip/xfail)는 사유를 적어야 한다 |
| 함수 순환복잡도 | **반드시** 10 이하 | Ruff `C901` (`max-complexity = 10`) |
| 함수 길이 | 순수 코드 50줄 이하 | 빈 줄, 주석 줄, docstring을 뺀 줄 수. 측정 스크립트는 코드 추가 시 함께 만든다 |
| 주석률 | 파일마다 20% 이상 | (주석 줄 + docstring 줄) ÷ (빈 줄을 뺀 전체 줄). 측정 스크립트는 코드 추가 시 함께 만든다 |
| 명명 규칙 | Google Python Style Guide | Ruff `N` 규칙(pep8-naming) |

- **커버리지 100%를 못 채웠을 때:** 달성할 때까지 테스트를 보강하며 반복한다.
  - `# pragma: no cover`로 측정에서 빼는 것은 사용자 승인 없이 하지 않는다.
  - 테스트로 도달할 수 없는 코드가 나오면, 코드 구조가 문제라는 신호로 보고 설계를 먼저 고친다.
- **명명 규칙:** 모듈·함수·변수·메서드는 `snake_case`, 클래스는 `CapWords`, 상수는 `UPPER_SNAKE_CASE`, 내부용 이름은 `_` 접두사를 쓴다.
- **주석 스타일:** 주석은 Doxygen 스타일을 쓴다. 이 점만은 Google 스타일 가이드보다 우선한다.
  - docstring을 `"""!`로 시작하고 `@brief`, `@param`, `@return`, `@raises`를 쓴다.
  - Google 형식 docstring 검사를 강제하는 Ruff의 docstring 규칙(`D`)은 켜지 않는다.

  ```python
  def add(a: int, b: int) -> int:
      """!
      @brief 두 정수를 더한다.
      @param a 첫 번째 정수
      @param b 두 번째 정수
      @return 두 정수의 합
      """
      return a + b
  ```

## Git 브랜치 규칙 (GitHub Flow + 태그)

- **`main`:** 항상 릴리스 가능한 상태를 유지한다. `main`에 직접 커밋하거나 push하지 않는다.
- **작업 브랜치:** 작업은 항상 `main`에서 새로 딴 브랜치에서 한다. 브랜치 이름은 영문 소문자와 하이픈으로 쓴다.

  | 유형 | 이름 형식 | 용도 |
  |---|---|---|
  | 기능 | `feature/<이슈번호>-<요약>` | 새 기능 |
  | 버그 수정 | `bugfix/<이슈번호>-<요약>` | 결함 수정 |
  | 긴급 수정 | `hotfix/<요약>` | 릴리스된 버전의 긴급 결함 |
  | 문서 | `docs/<요약>` | 문서만 바꿀 때 |
  | 기타 | `chore/<요약>` | 설정, 도구, 의존성 |

  이슈가 없으면 `<이슈번호>-`는 생략한다. 예: `feature/12-login-validation`, `chore/ruff-config`
- **커밋 메시지:** `<유형>: <한글 요약>` 형식으로 쓴다.
  - 유형: `feat`, `fix`, `refactor`, `test`, `docs`, `chore`
  - 예: `feat: 로그인 입력값 검증 추가`
  - 커밋 하나에는 논리적 변경 하나만 담는다.
- **PR:**
  - 작업 브랜치를 push한 뒤 `main`을 대상으로 PR을 만든다. PR 제목과 본문은 한글로 쓴다.
  - 본문에는 변경 내용, 관련 요구사항 ID, 품질 기준 충족 결과를 적는다.
  - 병합 조건은 Jenkins 품질 게이트 통과뿐이다. 리뷰어 승인은 필요 없다.
  - 품질 기준을 하나라도 만족하지 못하면 병합할 수 없다.
  - 병합은 Squash merge로 하고, 병합 후 작업 브랜치는 삭제한다.
  - Claude는 PR을 만들고 CI 결과까지 확인한다. 병합은 사용자가 지시할 때만 한다.
- **릴리스 기준선:** 릴리스할 때 `main`의 해당 커밋에 annotated 태그를 단다.
  - 태그 이름은 `vMAJOR.MINOR.PATCH` 형식이다(Semantic Versioning). 예: `git tag -a v1.0.0 -m "1.0.0 릴리스"`
  - 이 태그가 A-SPICE SUP.8(형상관리)의 기준선이다.

## CI (Jenkins)

- **서버:** Jenkins 2.580.2, `http://172.16.7.129`. 이 개발 PC에서 Windows 서비스(`Jenkins`, 계정 LocalSystem)로 동작한다. 빌드 노드는 내장 노드(Windows 11) 하나다.
- **작업:** Multibranch Pipeline `ClaudePython`
  - GitHub Branch Source로 저장소를 **5분마다 스캔**해 브랜치와 PR을 빌드한다. 사설 IP라 웹훅을 받을 수 없기 때문이다.
  - 빌드 결과는 GitHub Branch Source가 GitHub 커밋 상태로 보고한다.
  - 같은 서버에 있는 Freestyle 작업 `CluadePython`은 이 프로젝트와 무관한 기존 작업이라 건드리지 않는다.
- **인증 정보 (git에 저장 금지):**
  - Jenkins API: ID `admin`. 토큰은 Windows 사용자 환경 변수 `JENKINS_API_TOKEN`에만 있다. 명령에서 토큰 값을 직접 쓰지 말고 이 변수를 읽는다.
  - GitHub: Jenkins Credentials `github-claudepython`(사용자명/비밀번호 형식, gh 로그인 토큰)
- **파이프라인:** 저장소 최상위의 `Jenkinsfile`(Windows `bat`)이 아래 품질 게이트를 실행한다. 하나라도 실패하면 PR을 병합할 수 없다.
  1. `ruff check .`
  2. `ruff format --check .`
  3. `mypy` (strict, 명시적 Any 금지)
  4. `python -m pytest --cov --cov-branch --cov-fail-under=100`
  5. `python -m tools.check_metrics src tools`
- **Python 경로:** Jenkinsfile 기본값은 `C:\Users\user\AppData\Local\Programs\Python\Python312\python.exe`이다. Jenkins 전역 환경 변수 `PYTHON312`로 바꿀 수 있다.
- **빌드 결과 확인:** `GET http://172.16.7.129/job/ClaudePython/job/<브랜치 또는 PR-n>/lastBuild/api/json`. Basic 인증 `admin:%JENKINS_API_TOKEN%`. 스캔을 바로 돌리려면 `POST /job/ClaudePython/build`.

## 기타

- CLAUDE.md는 한글로 작성한다. 새로 추가하거나 고치는 내용도 모두 한글로 쓴다. 명령어, 경로, 코드 식별자는 원문 그대로 둔다.
- 모든 산출물은 한글로 작성한다. 문서, 주석, docstring, 커밋 메시지, PR, 테스트 케이스가 대상이다. 코드 식별자(변수명, 함수명 등)는 명명 규칙에 따라 영문으로 쓴다.
- **프롬프트 기록:** 사용자의 모든 프롬프트와 Claude의 답변을 저장소 최상위의 `prompt.md`에 순서대로 덧붙인다.
  - 형식은 `## N. Prompt` / `### Answer`이고, 항목 사이는 `---`로 구분한다.
  - 매 턴 빠짐없이 기록한다.
- 의미 없는 사과를 하지 않는다.
- 반말을 하지 않는다. 사용자에게는 존댓말을 쓴다.
