"""!
@brief tools.check_metrics 단위 테스트.

기대값은 모두 테스트 입력 소스를 직접 세어 얻은 리터럴이다.
"""

import runpy
import sys
import textwrap

import pytest

from tools.check_metrics import (
    check_source,
    comment_ratio,
    function_lengths,
    main,
)


def _src(text: str) -> str:
    """!
    @brief 들여쓰기를 제거한 테스트용 소스를 만든다.
    @param text 들여쓰기된 소스 문자열
    @return 들여쓰기가 제거된 소스
    """
    return textwrap.dedent(text).lstrip("\n")


def test_function_length_excludes_blank_comment_and_docstring_lines():
    # def 줄, x = 1, return x 만 순수 코드다 → 3줄
    source = _src(
        '''
        def f():
            """!
            @brief 설명
            """
            # 주석
            x = 1

            return x
        '''
    )
    assert function_lengths(source) == [("f", 1, 3)]


def test_function_length_counts_multiline_statement_lines():
    # def 줄 + 괄호로 이어진 3줄 → 4줄
    source = _src(
        """
        def g():
            return (
                1
            )
        """
    )
    assert function_lengths(source) == [("g", 1, 4)]


def test_function_length_reports_methods_and_nested_functions():
    source = _src(
        """
        class C:
            def m(self):
                def inner():
                    return 1
                return inner()
        """
    )
    # m: def m, def inner, return 1, return inner() → 4줄 / inner: 2줄
    assert function_lengths(source) == [("C.m", 2, 4), ("C.m.inner", 3, 2)]


def test_function_length_supports_async_functions():
    source = _src(
        """
        async def h():
            await x()
        """
    )
    assert function_lengths(source) == [("h", 1, 2)]


def test_comment_ratio_counts_docstring_and_inline_comment_lines():
    # 비어 있지 않은 줄 5 중 docstring 3줄 + 인라인 주석 1줄 → 4/5
    source = _src(
        '''
        """!
        @brief 모듈
        """
        x = 1  # 설명

        y = 2
        '''
    )
    assert comment_ratio(source) == pytest.approx(0.8)


def test_comment_ratio_is_zero_without_comments():
    assert comment_ratio("x = 1\ny = 2\n") == 0.0


def test_comment_ratio_ignores_hash_inside_string():
    assert comment_ratio('s = "# 주석 아님"\n') == 0.0


def test_comment_ratio_is_none_for_blank_source():
    assert comment_ratio("\n\n") is None


def _function_with_code_lines(n: int) -> str:
    """!
    @brief 순수 코드 n줄짜리 함수와 그 비율을 맞추는 주석을 가진 소스를 만든다.
    @param n 함수의 순수 코드 줄 수 (def 줄 포함)
    @return 주석률이 기준 이상인 소스
    """
    body = "".join(f"    x{i} = {i}  # 값\n" for i in range(n - 1))
    return "def f():\n" + body


def test_check_source_accepts_function_of_exactly_50_lines():
    assert check_source(_function_with_code_lines(50), "a.py") == []


def test_check_source_rejects_function_of_51_lines():
    assert check_source(_function_with_code_lines(51), "a.py") == [
        "a.py:1: 함수 'f' 순수 코드 51줄 (기준 50줄 이하)"
    ]


def test_check_source_accepts_comment_ratio_of_exactly_20_percent():
    source = "# 주석\n" + "x = 1\n" * 4  # 1/5 = 20%
    assert check_source(source, "b.py") == []


def test_check_source_rejects_comment_ratio_below_20_percent():
    source = "# 주석\n" + "x = 1\n" * 5  # 1/6 = 16.7%
    assert check_source(source, "b.py") == [
        "b.py: 주석률 16.7% (기준 20% 이상)"
    ]


def test_check_source_skips_blank_file():
    assert check_source("", "__init__.py") == []


def test_main_returns_zero_and_reports_ok_when_all_files_pass(tmp_path, capsys):
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "ok.py").write_text("x = 1  # 값\n", encoding="utf-8")
    assert main([str(tmp_path)]) == 0
    assert "위반 0건" in capsys.readouterr().out


def test_main_returns_one_and_lists_violations(tmp_path, capsys):
    bad = tmp_path / "bad.py"
    bad.write_text("x = 1\n", encoding="utf-8")
    assert main([str(bad)]) == 1
    out = capsys.readouterr().out
    assert f"{bad}: 주석률 0.0% (기준 20% 이상)" in out
    assert "위반 1건" in out


def test_module_entry_point_exits_with_main_result(tmp_path, monkeypatch):
    (tmp_path / "ok.py").write_text("x = 1  # 값\n", encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["check_metrics", str(tmp_path)])
    monkeypatch.delitem(sys.modules, "tools.check_metrics", raising=False)
    with pytest.raises(SystemExit) as exc:
        runpy.run_module("tools.check_metrics", run_name="__main__")
    assert exc.value.code == 0


def test_main_reports_missing_path_as_violation(tmp_path, capsys):
    missing = tmp_path / "없는경로"
    assert main([str(missing)]) == 1
    out = capsys.readouterr().out
    assert f"{missing}: 경로가 없습니다" in out
    assert "위반 1건" in out


def test_end_line_falls_back_to_start_line_when_end_is_missing():
    # ast.parse는 항상 end_lineno를 채우지만, 직접 만든 노드에는 없을 수 있다
    import ast

    from tools.check_metrics import _end_line

    node = ast.Pass(
        lineno=7, col_offset=0, end_lineno=None, end_col_offset=None
    )
    assert _end_line(node) == 7


def test_end_line_uses_end_line_when_present():
    import ast

    from tools.check_metrics import _end_line

    node = ast.Pass(lineno=3, col_offset=0, end_lineno=5, end_col_offset=0)
    assert _end_line(node) == 5
