#!/usr/bin/env python3
"""Reject staged or tracked paths and content unsafe for the public repository.

The pre-commit hook checks the index before a commit exists. CI checks the same
rules against the checkout as a backstop for skipped hooks and web uploads.
Only rule names and paths are printed; matched content is never echoed to logs.
"""

import argparse
import os
from pathlib import PurePosixPath
import re
import subprocess
import sys


EMAIL = re.compile(rb"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.IGNORECASE)
DIGIT_RUN = re.compile(r"[0-9]{3,}")
STREET_TYPE = re.compile(r"\b(?:Road|Rd|Street|St|Lane|Ln|Ave)\b|[號路街巷]", re.IGNORECASE)
SENSITIVE_NAMES = (
    "User Data Input",
    "customers",
    "settlements",
    "payments",
    "shipments",
    "purchase_orders",
    "product_master",
)


def git_output(*args: str) -> bytes:
    return subprocess.run(
        ["git", *args], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    ).stdout


def paths(mode: str) -> list[str]:
    if mode == "staged":
        raw = git_output("diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z")
    else:
        raw = git_output("ls-files", "-z")
    return [os.fsdecode(item) for item in raw.split(b"\0") if item]


def path_violations(path: str) -> list[str]:
    lower = path.casefold()
    filename = PurePosixPath(path).name.casefold()
    found = []
    if (filename == ".env" or filename.startswith(".env.")) and filename != ".env.example":
        found.append("env-file")
    if "state/" in lower or "inbox/" in lower:
        found.append("private-directory")
    if any(marker.casefold() in lower for marker in SENSITIVE_NAMES):
        found.append("sensitive-path")
    if lower.endswith((".csv", ".xlsx", ".xls")):
        fixture = lower.startswith("tests/fixtures/") and filename.endswith("_fixture.csv")
        if not fixture:
            found.append("tabular-file")
    if "__pycache__/" in lower or lower.endswith(".pyc"):
        found.append("python-cache")
    return found


def content_violations(path: str) -> list[str]:
    try:
        content = git_output("show", f":{path}")
    except subprocess.CalledProcessError:
        # Fail closed, including on a staged gitlink with no ordinary file body.
        return ["content-unreadable"]
    found = []
    if EMAIL.search(content):
        found.append("email-content")
    decoded = content.decode("utf-8", errors="replace")
    if any(DIGIT_RUN.search(line) and STREET_TYPE.search(line) for line in decoded.splitlines()):
        found.append("address-content")
    return found


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("staged", "tracked"), required=True)
    parser.add_argument("--check", choices=("all", "paths", "content"), default="all")
    args = parser.parse_args()

    try:
        candidates = paths(args.mode)
    except subprocess.CalledProcessError as exc:
        print(f"ERROR [guard-setup]: git command failed: {exc}", file=sys.stderr)
        return 2

    escape = args.mode == "staged" and os.environ.get("ALLOW_DATA_COMMIT") == "1"
    if escape:
        for path in candidates:
            print(f"WARNING [ALLOW_DATA_COMMIT=1] bypassing guard for {path!r}", file=sys.stderr)

    violations = []
    for path in candidates:
        if args.check in ("all", "paths"):
            violations.extend((rule, path) for rule in path_violations(path))
        if args.check in ("all", "content"):
            violations.extend((rule, path) for rule in content_violations(path))

    for rule, path in violations:
        level = "WARNING override" if escape else "ERROR"
        print(f"{level} [{rule}] {path!r}", file=sys.stderr)
    return 0 if escape or not violations else 1


if __name__ == "__main__":
    sys.exit(main())
