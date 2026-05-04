#!/usr/bin/env python3
"""Static checks to keep README structural claims aligned with repository reality."""

from __future__ import annotations

import re
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"

REQUIRED_PATHS = [
    "SKILL.md",
    "tools",
    "tools/core",
    "tools/services",
    "tools/config",
    "tools/mcp_server.py",
    "tools/schemas.py",
    "tools/wyckoff_utils.py",
    "tests",
]

REQUIRED_MENTIONS = [
    "SKILL.md",
    "tools/",
    "core/",
    "services/",
    "config/",
    "mcp_server.py",
    "schemas.py",
    "wyckoff_utils.py",
    "tests/",
]


def fail(msg: str) -> None:
    print(f"[FAIL] {msg}")
    sys.exit(1)


def main() -> None:
    if not README.exists():
        fail("README.md not found")

    text = README.read_text(encoding="utf-8")

    # 1) Ensure maintenance note exists.
    note = "说明：项目导航以仓库目录实际结构为准"
    if note not in text:
        fail("README is missing navigation maintenance note")

    # 2) Ensure last verification date exists and is valid ISO date.
    m = re.search(r"最后校验日期：`(\d{4}-\d{2}-\d{2})`", text)
    if not m:
        fail("README is missing '最后校验日期' in YYYY-MM-DD format")
    try:
        checked_date = date.fromisoformat(m.group(1))
    except ValueError:
        fail("README last verification date is not a valid date")
    if checked_date > date.today():
        fail("README last verification date cannot be in the future")

    # 3) Ensure README still references expected key paths and paths exist.
    missing_mentions = [p for p in REQUIRED_MENTIONS if p not in text]
    if missing_mentions:
        fail(f"README project navigation is missing path mentions: {missing_mentions}")

    missing_paths = [p for p in REQUIRED_PATHS if not (ROOT / p).exists()]
    if missing_paths:
        fail(f"Repository paths not found: {missing_paths}")

    print("[OK] README structural claims are valid.")


if __name__ == "__main__":
    main()
