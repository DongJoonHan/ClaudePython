# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

ClaudePython — AI를 이용한 파이썬 코드 (강사용). 강의용 Python 예제 코드를 Claude와 함께 작성하는 저장소입니다.

Current state: only `README.md` exists (single "Initial commit"). There is no build system, dependency manifest, linter config, or test suite yet — update this file once they are added.

## Environment

- Windows 11, PowerShell 5.1. Git and GitHub CLI (`gh`) were installed via winget; if they are not found in a fresh shell, refresh PATH:
  `$env:Path = [Environment]::GetEnvironmentVariable('Path','Machine') + ';' + [Environment]::GetEnvironmentVariable('Path','User')`
- Python 3.12 (winget, `C:\Users\user\AppData\Local\Programs\Python\Python312`) with `openpyxl`. The `WindowsApps\python.exe` Store stub may shadow it in a stale shell — refresh PATH as above.
- Microsoft PICT is installed at `%LOCALAPPDATA%\pict\pict.exe` (not on PATH; scripts find it via `ensure_pict.py`).

## Skills

- `.claude/skills/sw-system-test-case/` — generates A-SPICE SWE.6 / ISO 26262-6 system test cases as .xlsx. `SKILL.md` holds the workflow; `scripts/build_workbook.py` validates traceability/coverage from a JSON spec (format in `references/spec_format.md`) and renders the workbook (exit 2 = validation errors); `scripts/run_pict.py` generates pairwise combinations. When changing validation rules, keep `SKILL.md`, `references/spec_format.md` and the script's technique names in sync.
- Skill evals live in `.claude/skills/sw-system-test-case/evals/` (case-folder format); run outputs go to `.claude/skills/sw-system-test-case-workspace/iteration-N/`.

## Subagents

- `.claude/agents/system-test-case-generator.md` — runs on Sonnet and always uses the `sw-system-test-case` skill (preloaded via `skills:`). Intended for the stage after SW requirements analysis is complete; it returns questions to the caller instead of asking the user.
- Remote: `https://github.com/DongJoonHan/ClaudePython.git` (branch `main`). Pushing requires `gh auth login`.

## Implementation workflow (TDD required)

- Before writing any implementation code — new features, bug fixes, refactoring, behavior changes (including the skill scripts under `.claude/skills/*/scripts/`) — invoke the `test-driven-development` skill and follow its Red-Green-Refactor cycle: write a failing test, run it and watch it fail for the expected reason, write minimal code, run the full suite.
- Test runner: `python -m pytest` (whole suite) / `python -m pytest path/to/test_x.py::test_name` (single test). pytest 9.2 is installed. Put tests in `tests/` mirroring the source layout.
- Exceptions the skill allows (throwaway prototypes, generated code, config files) still require asking the user first.
- The skill is vendored from https://github.com/obra/superpowers (MIT, commit 22f0b46) at `.claude/skills/test-driven-development/`. To update it, re-copy `skills/test-driven-development/` from upstream.

## Conventions

- **Prompt log:** The user asked that every prompt and Claude's answer be appended to `prompt.md` in the repo root, numbered sequentially (`## N. Prompt` / `### Answer`, separated by `---`). Keep doing this each turn.
- Communicate with the user in Korean.
