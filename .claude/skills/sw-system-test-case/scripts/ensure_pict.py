#!/usr/bin/env python3
"""Locate Microsoft PICT (https://github.com/microsoft/pict); install it from the official GitHub release if missing.

Usage:  python ensure_pict.py        -> prints the absolute path of the pict executable
Exit code 0 on success, 1 if PICT is unavailable (with instructions on stderr).
"""
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

RELEASE_URL = "https://github.com/microsoft/pict/releases/latest/download/pict.exe"
IS_WINDOWS = platform.system() == "Windows"


def install_dir() -> Path:
    if IS_WINDOWS:
        return Path(os.environ.get("LOCALAPPDATA", Path.home())) / "pict"
    return Path.home() / ".local" / "bin"


def candidate() -> Path:
    return install_dir() / ("pict.exe" if IS_WINDOWS else "pict")


def works(path: str) -> bool:
    """Run PICT on a trivial model to confirm the binary is usable."""
    with tempfile.TemporaryDirectory() as tmp:
        model = Path(tmp) / "m.txt"
        model.write_text("A: 1, 2\nB: 1, 2\n", encoding="utf-8")
        try:
            out = subprocess.run([path, str(model)], capture_output=True, timeout=30)
        except (OSError, subprocess.TimeoutExpired):
            return False
        return out.returncode == 0 and b"A" in out.stdout


def find_pict():
    for p in (shutil.which("pict"), str(candidate()) if candidate().exists() else None):
        if p and works(p):
            return p
    return None


def ensure_pict() -> str:
    found = find_pict()
    if found:
        return found
    if not IS_WINDOWS:
        raise RuntimeError(
            "PICT not found. Build it from the official repository:\n"
            "  git clone https://github.com/microsoft/pict.git && cd pict\n"
            "  cmake -DCMAKE_BUILD_TYPE=Release -S . -B build && cmake --build build\n"
            f"  cp build/cli/pict {candidate()}"
        )
    target = candidate()
    target.parent.mkdir(parents=True, exist_ok=True)
    print(f"Downloading PICT from {RELEASE_URL} -> {target}", file=sys.stderr)
    urllib.request.urlretrieve(RELEASE_URL, target)
    if not works(str(target)):
        raise RuntimeError(f"Downloaded PICT at {target} does not run.")
    return str(target)


if __name__ == "__main__":
    try:
        print(ensure_pict())
    except Exception as exc:  # noqa: BLE001 - report any failure to the caller
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
