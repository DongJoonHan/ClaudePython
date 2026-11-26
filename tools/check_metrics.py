"""!
@brief 함수 길이와 주석률을 측정하는 품질 지표 도구.

CLAUDE.md의 소스코드 품질 기준을 측정한다.
- 함수 길이: 빈 줄, 주석 줄, docstring 줄을 뺀 순수 코드 줄 수 (50줄 이하)
- 주석률: (주석 줄 ∪ docstring 줄) ÷ 빈 줄을 뺀 전체 줄 (파일마다 20% 이상)

사용법: python -m tools.check_metrics src tools
"""

import ast
import io
import sys
import tokenize
from collections.abc import Iterator
from pathlib import Path

## 함수 하나의 순수 코드 줄 수 상한
MAX_FUNCTION_LINES = 50
## 파일 하나의 주석률 하한
MIN_COMMENT_RATIO = 0.20

# 코드로 세지 않는 토큰 종류 (주석, 줄바꿈, 들여쓰기 등)
_NON_CODE_TOKENS = frozenset(
    {
        tokenize.COMMENT,
        tokenize.NL,
        tokenize.NEWLINE,
        tokenize.INDENT,
        tokenize.DEDENT,
        tokenize.ENDMARKER,
    }
)

# docstring을 가질 수 있는 노드 종류
_DOC_OWNERS = (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)

_FUNCTIONS = (ast.FunctionDef, ast.AsyncFunctionDef)


def _docstring_lines(tree: ast.AST) -> set[int]:
    """!
    @brief 모듈, 클래스, 함수 docstring이 차지하는 줄 번호를 모은다.
    @param tree 분석할 AST
    @return docstring 줄 번호 집합
    """
    lines: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, _DOC_OWNERS) and ast.get_docstring(node):
            expr = node.body[0]
            lines.update(range(expr.lineno, expr.end_lineno + 1))
    return lines


def _code_lines(source: str, doc_lines: set[int]) -> set[int]:
    """!
    @brief 코드 토큰이 있는 줄 번호를 모은다 (docstring 줄 제외).
    @param source 분석할 소스
    @param doc_lines 제외할 docstring 줄 번호
    @return 순수 코드 줄 번호 집합
    """
    lines: set[int] = set()
    tokens = tokenize.generate_tokens(io.StringIO(source).readline)
    for tok in tokens:
        if tok.type in _NON_CODE_TOKENS:
            continue
        # 여러 줄에 걸친 토큰(문자열 등)은 걸친 줄을 모두 센다
        span = range(tok.start[0], tok.end[0] + 1)
        lines.update(n for n in span if n not in doc_lines)
    return lines


def _walk_functions(
    node: ast.AST, prefix: str
) -> Iterator[tuple[str, ast.AST]]:
    """!
    @brief 함수 노드를 정규화된 이름(클래스.메서드.내부함수)과 함께 순회한다.
    @param node 탐색을 시작할 노드
    @param prefix 상위 스코프 이름 접두사
    @return (정규화 이름, 함수 노드) 이터레이터
    """
    for child in ast.iter_child_nodes(node):
        if isinstance(child, _FUNCTIONS):
            name = prefix + child.name
            yield name, child
            yield from _walk_functions(child, name + ".")
        elif isinstance(child, ast.ClassDef):
            yield from _walk_functions(child, prefix + child.name + ".")
        else:
            yield from _walk_functions(child, prefix)


def comment_ratio(source: str) -> float | None:
    """!
    @brief 주석률을 계산한다.

    주석률 = (주석 토큰이 있는 줄 ∪ docstring 줄) ÷ 빈 줄을 뺀 전체 줄
    @param source 분석할 Python 소스
    @return 0.0~1.0 주석률, 빈 줄만 있는 소스는 None
    """
    total = sum(1 for line in source.splitlines() if line.strip())
    if total == 0:
        return None
    commented = _docstring_lines(ast.parse(source))
    tokens = tokenize.generate_tokens(io.StringIO(source).readline)
    commented.update(t.start[0] for t in tokens if t.type == tokenize.COMMENT)
    return len(commented) / total


def function_lengths(source: str) -> list[tuple[str, int, int]]:
    """!
    @brief 소스 안 모든 함수의 순수 코드 줄 수를 계산한다.
    @param source 분석할 Python 소스
    @return (정규화 이름, 시작 줄, 순수 코드 줄 수) 목록 (출현 순서)
    """
    tree = ast.parse(source)
    code = _code_lines(source, _docstring_lines(tree))
    result = []
    for name, func in _walk_functions(tree, ""):
        span = range(func.lineno, func.end_lineno + 1)
        result.append((name, func.lineno, sum(1 for n in span if n in code)))
    return result


def check_source(source: str, path: str) -> list[str]:
    """!
    @brief 소스 하나를 품질 기준으로 판정한다.
    @param source 분석할 Python 소스
    @param path 위반 메시지에 표시할 파일 경로
    @return 위반 메시지 목록 (위반이 없으면 빈 목록)
    """
    violations = [
        f"{path}:{line}: 함수 '{name}' 순수 코드 {n}줄 "
        f"(기준 {MAX_FUNCTION_LINES}줄 이하)"
        for name, line, n in function_lengths(source)
        if n > MAX_FUNCTION_LINES
    ]
    ratio = comment_ratio(source)
    if ratio is not None and ratio < MIN_COMMENT_RATIO:
        violations.append(
            f"{path}: 주석률 {ratio:.1%} (기준 {MIN_COMMENT_RATIO:.0%} 이상)"
        )
    return violations


def _python_files(paths: list[str]) -> list[Path]:
    """!
    @brief 경로 목록에서 검사할 .py 파일을 모은다 (디렉터리는 재귀 탐색).
    @param paths 파일 또는 디렉터리 경로 목록
    @return 정렬된 .py 파일 경로 목록
    """
    files: list[Path] = []
    for raw in paths:
        p = Path(raw)
        files.extend(sorted(p.rglob("*.py")) if p.is_dir() else [p])
    return files


def main(argv: list[str]) -> int:
    """!
    @brief 지정한 경로의 파일을 검사하고 결과를 출력한다.
    @param argv 검사할 파일 또는 디렉터리 경로 목록
    @return 위반이 없으면 0, 있으면 1
    """
    violations = []
    for file in _python_files(argv):
        if not file.exists():
            # 잘못된 경로를 통과로 보고하지 않도록 위반으로 센다
            violations.append(f"{file}: 경로가 없습니다")
            continue
        source = file.read_text(encoding="utf-8")
        violations.extend(check_source(source, str(file)))
    for message in violations:
        print(message)
    print(f"품질 지표 검사: 위반 {len(violations)}건")
    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
