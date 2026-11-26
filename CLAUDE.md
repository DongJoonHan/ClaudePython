# CLAUDE.md

이 파일은 Claude Code(claude.ai/code)가 이 저장소에서 작업할 때 참고하는 안내서이다.

## 프로젝트

ClaudePython: AI를 이용한 파이썬 코드(강사용). 강의용 Python 예제 코드를 Claude와 함께 작성하는 저장소이다.

현재 상태: 강의용 Python 코드는 아직 없다. 저장소에는 Claude 스킬, 서브에이전트, 설정 파일만 있다. `pyproject.toml`, Ruff 설정, `Jenkinsfile`도 아직 없으며, 코드를 처음 추가할 때 함께 만든다.

## 개발 환경

- **언어:** Python 최신 안정 버전을 사용한다.
  - 현재 개발 PC에는 Python 3.12.10이 설치되어 있다.
  - 최소 지원 버전은 `pyproject.toml`의 `requires-python`에 명시한다.
  - 버전을 올리면 이 항목을 갱신한다.
- **단위 테스트:** pytest를 사용하고, 브랜치 커버리지는 pytest-cov로 측정한다.
  - 전체 실행: `python -m pytest --cov=src --cov-branch --cov-report=term-missing --cov-fail-under=100`
  - 개별 실행: `python -m pytest tests/path/test_x.py::test_name`
- **정적 분석:** Ruff를 사용한다. 설정은 `pyproject.toml`의 `[tool.ruff]`에 둔다.
  - 검사: `ruff check .`
  - 포맷 확인: `ruff format --check .`
- **디렉터리:** 소스는 `src/`, 테스트는 `tests/`에 두고, `tests/`는 `src/`와 같은 구조로 만든다.

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

- CI는 Jenkins를 쓴다. Jenkins 서버 주소는 `172.16.7.129`이다.
- 파이프라인은 저장소 최상위의 `Jenkinsfile`에 정의하고, PR마다 아래 품질 게이트를 실행한다. 하나라도 실패하면 PR을 병합할 수 없다.
  1. `ruff check .`
  2. `ruff format --check .`
  3. `python -m pytest --cov=src --cov-branch --cov-fail-under=100`
  4. 함수 길이·주석률 측정 스크립트
- **확인 필요:** 아래 항목은 아직 정해지지 않았다. 정해지면 이 절에 적는다.
  - Jenkins가 GitHub PR 빌드를 시작하는 방법. `172.16.7.129`는 사설 IP라 GitHub의 웹훅이 바로 닿지 않는다. SCM 폴링이나 중계 같은 방법이 필요하다.
  - Jenkins 접속 포트와 URL
  - 빌드 결과를 GitHub PR 상태로 보고하는 방법

## 기타

- CLAUDE.md는 한글로 작성한다. 새로 추가하거나 고치는 내용도 모두 한글로 쓴다. 명령어, 경로, 코드 식별자는 원문 그대로 둔다.
- 모든 산출물은 한글로 작성한다. 문서, 주석, docstring, 커밋 메시지, PR, 테스트 케이스가 대상이다. 코드 식별자(변수명, 함수명 등)는 명명 규칙에 따라 영문으로 쓴다.
- **프롬프트 기록:** 사용자의 모든 프롬프트와 Claude의 답변을 저장소 최상위의 `prompt.md`에 순서대로 덧붙인다.
  - 형식은 `## N. Prompt` / `### Answer`이고, 항목 사이는 `---`로 구분한다.
  - 매 턴 빠짐없이 기록한다.
- 의미 없는 사과를 하지 않는다.
- 반말을 하지 않는다. 사용자에게는 존댓말을 쓴다.
