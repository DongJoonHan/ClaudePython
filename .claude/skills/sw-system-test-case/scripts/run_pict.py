#!/usr/bin/env python3
"""Run Microsoft PICT on a model file and emit the generated combinations as JSON.

Usage:
  python run_pict.py <model.txt> [--order 2] [--seed N] [--out result.json]

Output JSON: {"model_file", "model_text", "command", "header": [...], "rows": [{param: value}, ...]}
Paste "model_text" and "command" into the spec's pict_models entry so the result is reproducible.
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ensure_pict import ensure_pict  # noqa: E402


def decode(data: bytes) -> str:
    for enc in ("utf-8-sig", "cp949", "latin-1"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("model")
    ap.add_argument("--order", type=int, default=2, help="combination strength (/o), default 2 = pairwise")
    ap.add_argument("--seed", type=int, help="random seed (/r:N) for reproducible output")
    ap.add_argument("--out", help="write JSON here instead of stdout")
    args = ap.parse_args()

    pict = ensure_pict()
    model_path = Path(args.model).resolve()
    cmd = [pict, str(model_path), f"/o:{args.order}"]
    if args.seed is not None:
        cmd.append(f"/r:{args.seed}")
    proc = subprocess.run(cmd, capture_output=True)
    if proc.returncode != 0:
        print(decode(proc.stderr) or decode(proc.stdout), file=sys.stderr)
        return proc.returncode

    lines = [ln for ln in decode(proc.stdout).splitlines() if ln.strip()]
    header = lines[0].split("\t")
    rows = [dict(zip(header, ln.split("\t"))) for ln in lines[1:]]
    shown_cmd = " ".join(["pict", model_path.name] + cmd[2:])
    result = {
        "model_file": str(model_path),
        "model_text": decode(model_path.read_bytes()),
        "command": shown_cmd,
        "header": header,
        "rows": rows,
    }
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
        print(f"{len(rows)} combinations -> {args.out}")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
