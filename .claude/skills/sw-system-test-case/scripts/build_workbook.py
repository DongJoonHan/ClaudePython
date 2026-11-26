#!/usr/bin/env python3
"""Validate a system-test-case spec (JSON) and render it to an .xlsx workbook.

Usage:
  python build_workbook.py spec.json out.xlsx [--template customer.xlsx] [--allow-gaps]

The spec format is documented in references/spec_format.md.
Exit code: 0 = workbook written, validation passed (warnings may exist)
           2 = validation errors (no workbook written) - fix the spec and re-run
"""
import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

# (field key, default header, column width)
DEFAULT_COLUMNS = [
    ("id", "테스트 케이스 ID", 16),
    ("kind", "구분", 8),
    ("basis_ids", "테스트 베이시스 ID", 18),
    ("purpose", "테스트 목적", 36),
    ("preconditions", "사전 조건", 30),
    ("environment", "테스트 환경", 16),
    ("inputs", "입력값", 36),
    ("procedure", "절차", 48),
    ("expected", "예상 출력값", 42),
    ("techniques", "사용한 테스트 기법", 20),
]
REQUIRED_FIELDS = ["id", "category", "basis_ids", "purpose", "inputs", "procedure", "expected", "techniques"]
# Fields that must have a column in the output (the user's mandatory items + the 제안 marker).
MANDATORY_OUTPUT = ["id", "basis_ids", "purpose", "inputs", "procedure", "expected", "techniques", "kind"]
CATEGORY_SHEETS = {"기능": "기능 테스트", "비기능": "비기능 테스트"}
PAIRWISE = "페어와이즈(PICT)"
KNOWN_TECHNIQUES = {
    "경계값 분석", "동치 분할", PAIRWISE, "WoW 검증", "요구사항 분석", "오류 추측",
    "폴트 주입", "상태 전이", "기능 의존성 분석", "운용 시나리오 분석", "성능 측정",
}
VAGUE_PATTERNS = ["정상적으로", "정상 동작", "올바르게", "적절히", "적절하게", "문제없이", "잘 동작", "등등", "기타 등"]

HEADER_FILL = PatternFill("solid", fgColor="1F4E78")
HEADER_FONT = Font(bold=True, color="FFFFFF")
PROPOSED_FILL = PatternFill("solid", fgColor="FFF2CC")
GAP_FILL = PatternFill("solid", fgColor="F8CBAD")
THIN = Side(style="thin", color="A6A6A6")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
WRAP = Alignment(wrap_text=True, vertical="top")


# ---------------------------------------------------------------- formatting helpers
def as_list(value):
    if value is None or value == "":
        return []
    return value if isinstance(value, list) else [value]


def fmt(field, value):
    """Render a spec value as cell text."""
    if value is None:
        return ""
    if field == "procedure" and isinstance(value, list):
        return "\n".join(f"{i}. {step}" for i, step in enumerate(value, 1))
    if isinstance(value, dict):
        return "\n".join(f"{k} = {v}" for k, v in value.items())
    if isinstance(value, list):
        sep = ", " if field in ("basis_ids", "techniques") else "\n"
        return sep.join(fmt(field, v) for v in value)
    return str(value)


def tc_cell(tc, field):
    if field == "kind":
        return "제안" if tc.get("proposed") else "기본"
    return fmt(field, tc.get(field))


# ---------------------------------------------------------------- validation
def validate(spec, allow_gaps):
    errors, warnings = [], []
    basis = spec.get("basis", [])
    tcs = spec.get("test_cases", [])
    basis_ids = [b.get("id") for b in basis]
    basis_set = set(basis_ids)
    models = {m.get("id"): m for m in spec.get("pict_models", [])}

    if not basis:
        errors.append("basis가 비어 있습니다. 테스트 베이시스 항목을 모두 나열하세요.")
    if not tcs:
        errors.append("test_cases가 비어 있습니다.")
    for bid, n in Counter(basis_ids).items():
        if n > 1:
            errors.append(f"베이시스 ID 중복: {bid}")
    for tid, n in Counter(tc.get("id") for tc in tcs).items():
        if n > 1:
            errors.append(f"테스트 케이스 ID 중복: {tid}")

    covered = defaultdict(list)
    model_usage = Counter()
    signature = defaultdict(list)
    for tc in tcs:
        tid = tc.get("id", "<id 없음>")
        for f in REQUIRED_FIELDS:
            if not as_list(tc.get(f)) and not (isinstance(tc.get(f), dict) and tc.get(f)):
                errors.append(f"{tid}: 필수 항목 '{f}' 누락")
        if tc.get("category") not in CATEGORY_SHEETS:
            errors.append(f"{tid}: category는 '기능' 또는 '비기능'이어야 합니다 (현재: {tc.get('category')!r})")
        for bid in as_list(tc.get("basis_ids")):
            if bid not in basis_set:
                errors.append(f"{tid}: 존재하지 않는 베이시스 ID '{bid}' 참조 (추적성 오류)")
            else:
                covered[bid].append(tid)
        techs = as_list(tc.get("techniques"))
        for t in techs:
            if t not in KNOWN_TECHNIQUES:
                warnings.append(f"{tid}: 표준 기법명 목록에 없는 기법 '{t}' - 의도한 것인지 확인")
        if PAIRWISE in techs:
            mid = tc.get("pict_model")
            if mid not in models:
                errors.append(f"{tid}: 페어와이즈 케이스는 PICT로 도출해야 합니다. pict_model이 pict_models의 id를 가리켜야 합니다.")
            else:
                model_usage[mid] += 1
        text = fmt("expected", tc.get("expected"))
        for pat in VAGUE_PATTERNS:
            if pat in text:
                warnings.append(f"{tid}: 예상 출력값에 모호한 표현 '{pat}' - 관측 가능한 값/상태/시간으로 구체화")
        signature[(fmt("inputs", tc.get("inputs")), fmt("preconditions", tc.get("preconditions")), text)].append(tid)

    for ids in signature.values():
        if len(ids) > 1:
            warnings.append(f"사전조건·입력·예상 출력이 동일한 중복 의심 케이스: {', '.join(ids)}")

    for mid, m in models.items():
        rows = m.get("rows")
        if not m.get("model_text"):
            errors.append(f"PICT 모델 {mid}: model_text 누락 (재현성)")
        if isinstance(rows, list) and model_usage[mid] and model_usage[mid] != len(rows):
            warnings.append(
                f"PICT 모델 {mid}: 생성 조합 {len(rows)}개 중 {model_usage[mid]}개만 케이스화됨 - 누락/병합 사유를 notes에 기록"
            )

    gaps = []
    for b in basis:
        bid = b.get("id")
        if covered.get(bid):
            continue
        gaps.append(bid)
        reason = b.get("not_testable_reason")
        msg = f"베이시스 {bid} 미커버" + (f" (사유: {reason})" if reason else "")
        (warnings if allow_gaps else errors).append(msg)

    has = {t for tc in tcs for t in as_list(tc.get("techniques"))}
    for must in ("경계값 분석", "동치 분할"):
        if tcs and must not in has:
            errors.append(f"필수 기법 '{must}'이 어떤 케이스에도 적용되지 않았습니다.")
    for b in basis:
        techs = {t for tid in covered.get(b.get("id"), []) for tc in tcs if tc.get("id") == tid for t in as_list(tc.get("techniques"))}
        if techs and not techs & {"경계값 분석", "동치 분할"} and not b.get("ep_bva_na_reason"):
            warnings.append(f"베이시스 {b.get('id')}: 경계값/동치 기법 미적용 - 적용 불가하면 ep_bva_na_reason 기록")

    return errors, warnings, covered, gaps


# ---------------------------------------------------------------- sheet writers
def style_header(ws, row, ncols):
    for c in range(1, ncols + 1):
        cell = ws.cell(row=row, column=c)
        cell.fill, cell.font, cell.border = HEADER_FILL, HEADER_FONT, BORDER
        cell.alignment = Alignment(wrap_text=True, vertical="center", horizontal="center")


def write_table(ws, headers, rows, widths=None, start_row=1, fills=None):
    for c, h in enumerate(headers, 1):
        ws.cell(row=start_row, column=c, value=h)
    style_header(ws, start_row, len(headers))
    for r, row in enumerate(rows, start_row + 1):
        for c, v in enumerate(row, 1):
            cell = ws.cell(row=r, column=c, value=v)
            cell.alignment, cell.border = WRAP, BORDER
            if fills and fills[r - start_row - 1]:
                cell.fill = fills[r - start_row - 1]
    if widths:
        for c, w in enumerate(widths, 1):
            ws.column_dimensions[get_column_letter(c)].width = w
    ws.freeze_panes = ws.cell(row=start_row + 1, column=2)


def write_tc_sheet_default(ws, tcs, columns):
    rows = [[tc_cell(tc, key) for key, _, _ in columns] for tc in tcs]
    fills = [PROPOSED_FILL if tc.get("proposed") else None for tc in tcs]
    write_table(ws, [h for _, h, _ in columns], rows, [w for _, _, w in columns], fills=fills)
    if not tcs:
        ws.cell(row=2, column=1, value="해당 없음 (이 유형의 테스트 베이시스 항목이 없습니다)")


def find_header_row(ws, wanted_headers, explicit=None):
    if explicit:
        return explicit
    best, best_hits = 1, -1
    for r in range(1, min(ws.max_row, 30) + 1):
        values = {str(ws.cell(row=r, column=c).value).strip() for c in range(1, ws.max_column + 1) if ws.cell(row=r, column=c).value}
        hits = len(values & wanted_headers)
        if hits > best_hits:
            best, best_hits = r, hits
    return best


def write_tc_sheet_template(ws, tcs, mapping, header_row, warnings):
    """Fill a customer template sheet. mapping: field key -> header text in the template."""
    header_row = find_header_row(ws, set(mapping.values()), header_row)
    col_of = {}
    for c in range(1, ws.max_column + 1):
        v = ws.cell(row=header_row, column=c).value
        if v is not None:
            for key, header in mapping.items():
                if str(v).strip() == header:
                    col_of[key] = c
    defaults = {k: h for k, h, _ in DEFAULT_COLUMNS}
    for key in MANDATORY_OUTPUT:
        if key not in col_of:
            c = ws.max_column + 1
            cell = ws.cell(row=header_row, column=c, value=defaults[key])
            cell.fill, cell.font, cell.border = HEADER_FILL, HEADER_FONT, BORDER
            col_of[key] = c
            warnings.append(f"[{ws.title}] 양식에 '{defaults[key]}' 열이 없어 마지막 열에 추가했습니다.")
    for i, tc in enumerate(tcs, header_row + 1):
        for key, c in col_of.items():
            cell = ws.cell(row=i, column=c, value=tc_cell(tc, key))
            cell.alignment, cell.border = WRAP, BORDER
            if tc.get("proposed"):
                cell.fill = PROPOSED_FILL


def write_traceability(ws, spec, covered):
    tc_by_id = {tc["id"]: tc for tc in spec["test_cases"] if "id" in tc}
    rows, fills = [], []
    for b in spec["basis"]:
        ids = covered.get(b["id"], [])
        techs = sorted({t for tid in ids for t in as_list(tc_by_id[tid].get("techniques"))})
        n_prop = sum(1 for tid in ids if tc_by_id[tid].get("proposed"))
        status = "커버" if ids else ("미커버 - " + b.get("not_testable_reason", "사유 미기재"))
        rows.append([b["id"], b.get("title", ""), b.get("type", ""), b.get("asil", ""),
                     len(ids), n_prop, ", ".join(ids), ", ".join(techs), status])
        fills.append(None if ids else GAP_FILL)
    write_table(ws, ["베이시스 ID", "요구사항 요약", "유형", "ASIL", "TC 수", "제안 TC 수",
                     "테스트 케이스 ID", "적용 기법", "상태"], rows,
                [16, 40, 10, 8, 8, 10, 40, 30, 24], fills=fills)


def write_coverage(ws, spec, covered, gaps):
    basis, tcs = spec["basis"], spec["test_cases"]
    total = len(basis)
    n_cov = total - len(gaps)
    traced = sum(1 for tc in tcs if as_list(tc.get("basis_ids")))
    tech_count = Counter(t for tc in tcs for t in as_list(tc.get("techniques")))
    rows = [
        ["테스트 베이시스", spec.get("basis_document", "")],
        ["테스트 베이시스 항목 수", total],
        ["커버된 항목 수", n_cov],
        ["테스트 베이시스 커버리지", f"{(n_cov / total * 100) if total else 0:.1f}%"],
        ["테스트 케이스 수 (전체)", len(tcs)],
        ["  기능 / 비기능", f"{sum(1 for t in tcs if t.get('category') == '기능')} / {sum(1 for t in tcs if t.get('category') == '비기능')}"],
        ["  기본 / 제안", f"{sum(1 for t in tcs if not t.get('proposed'))} / {sum(1 for t in tcs if t.get('proposed'))}"],
        ["베이시스로 추적되는 TC 비율", f"{(traced / len(tcs) * 100) if tcs else 0:.1f}%"],
        ["미커버 항목", ", ".join(gaps) if gaps else "없음"],
    ]
    rows += [[f"기법: {t}", n] for t, n in sorted(tech_count.items())]
    write_table(ws, ["지표", "값"], rows, [34, 60])


def write_assumptions(ws, spec):
    items = spec.get("assumptions", [])
    rows = [[a.get("id", ""), a.get("type", ""), fmt("x", a.get("related_basis")), a.get("content", ""), a.get("impact", "")] for a in items]
    write_table(ws, ["ID", "구분(가정/질의)", "관련 베이시스", "내용", "영향 받는 TC/조치"], rows, [10, 14, 18, 60, 30])


def write_pict(ws, spec):
    rows = []
    for m in spec.get("pict_models", []):
        n = len(m["rows"]) if isinstance(m.get("rows"), list) else m.get("rows", "")
        rows.append([m.get("id", ""), fmt("x", m.get("basis_ids")), m.get("command", ""), m.get("model_text", ""), n, m.get("notes", "")])
    write_table(ws, ["모델 ID", "관련 베이시스", "실행 명령", "PICT 모델", "생성 조합 수", "비고"], rows, [10, 18, 24, 60, 12, 40])


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("spec")
    ap.add_argument("out")
    ap.add_argument("--template", help="customer .xlsx template to fill instead of the default layout")
    ap.add_argument("--allow-gaps", action="store_true",
                    help="write the workbook even if basis items are uncovered (gaps are still reported)")
    args = ap.parse_args()

    spec = json.loads(Path(args.spec).read_text(encoding="utf-8"))
    errors, warnings, covered, gaps = validate(spec, args.allow_gaps)
    if errors:
        print("VALIDATION ERRORS (workbook not written):")
        for e in errors:
            print("  -", e)
        if warnings:
            print("WARNINGS:")
            for w in warnings:
                print("  -", w)
        return 2

    by_cat = {c: [tc for tc in spec["test_cases"] if tc["category"] == c] for c in CATEGORY_SHEETS}
    tpl = spec.get("template", {})
    if args.template:
        wb = load_workbook(args.template)
        mapping = tpl.get("columns") or {k: h for k, h, _ in DEFAULT_COLUMNS}
        base = wb[tpl["sheet"]] if tpl.get("sheet") in wb.sheetnames else wb.worksheets[0]
        for cat, sheet_name in CATEGORY_SHEETS.items():
            target_name = tpl.get(f"sheet_{'functional' if cat == '기능' else 'nonfunctional'}", sheet_name)
            ws = wb[target_name] if target_name in wb.sheetnames else wb.copy_worksheet(base)
            ws.title = target_name
            write_tc_sheet_template(ws, by_cat[cat], mapping, tpl.get("header_row"), warnings)
    else:
        wb = Workbook()
        wb.remove(wb.active)
        for cat, sheet_name in CATEGORY_SHEETS.items():
            write_tc_sheet_default(wb.create_sheet(sheet_name), by_cat[cat], DEFAULT_COLUMNS)

    write_traceability(wb.create_sheet("추적성 매트릭스"), spec, covered)
    write_coverage(wb.create_sheet("커버리지 요약"), spec, covered, gaps)
    if spec.get("assumptions"):
        write_assumptions(wb.create_sheet("가정 및 질의"), spec)
    if spec.get("pict_models"):
        write_pict(wb.create_sheet("페어와이즈 모델"), spec)

    wb.save(args.out)
    total = len(spec["basis"])
    print(f"Workbook written: {args.out}")
    print(f"  basis coverage: {total - len(gaps)}/{total}  |  test cases: {len(spec['test_cases'])} "
          f"(기능 {len(by_cat['기능'])}, 비기능 {len(by_cat['비기능'])}, 제안 {sum(1 for t in spec['test_cases'] if t.get('proposed'))})")
    if warnings:
        print("WARNINGS (review each one):")
        for w in warnings:
            print("  -", w)
    return 0


if __name__ == "__main__":
    sys.exit(main())
