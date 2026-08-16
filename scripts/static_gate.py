from __future__ import annotations

import ast
import subprocess
from pathlib import Path


LOCAL_SECRET_FILES = {".env", ".env.local"}
SKIP_DIR_NAMES = {".venv", "__pycache__", ".pytest_cache", ".git", "runtime"}
SKIP_SUFFIXES = {".zip", ".db", ".pyc", ".sqlite", ".sqlite3"}


def _is_runtime_or_generated(path: Path, root: Path) -> bool:
    rel = path.relative_to(root)
    return any(part in SKIP_DIR_NAMES for part in rel.parts) or path.suffix.lower() in SKIP_SUFFIXES


def _git_tracked(root: Path, relative_path: str) -> bool:
    """Return True only when a local Git repository explicitly tracks the path.

    Phase archives are intentionally usable before `git init`, so absence of Git metadata is
    not an error. When Git metadata exists, a local secret file being tracked is a hard fail.
    """
    if not (root / ".git").exists():
        return False
    result = subprocess.run(
        ["git", "ls-files", "--error-unmatch", "--", relative_path],
        cwd=root,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return result.returncode == 0


def scan_root(root: Path) -> list[str]:
    failures: list[str] = []

    # Python syntax / unfinished-development markers.
    for path in [*root.glob("src/**/*.py"), *root.glob("tests/**/*.py"), *root.glob("scripts/*.py")]:
        text = path.read_text(encoding="utf-8")
        try:
            ast.parse(text, filename=str(path))
        except SyntaxError as exc:
            failures.append(f"syntax: {path}: {exc}")
        for marker in ("TO" + "DO", "FIX" + "ME"):
            if marker in text:
                failures.append(f"unfinished marker {marker}: {path}")

    # A repository-local .env is REQUIRED for credential-backed Windows acceptance. It is
    # runtime state, not source. The release invariant is therefore: ignore it publicly and
    # never track/package it. Do not read or echo its contents during static validation.
    gitignore = root / ".gitignore"
    ignored_lines = set()
    if gitignore.exists():
        ignored_lines = {
            line.strip()
            for line in gitignore.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        }
    if ".env" not in ignored_lines:
        failures.append("secret hygiene: .gitignore must contain an explicit .env rule")

    for secret_name in sorted(LOCAL_SECRET_FILES):
        if _git_tracked(root, secret_name):
            failures.append(f"secret hygiene: local secret file is Git-tracked: {secret_name}")

    # Scan repository SOURCE for accidentally embedded secret assignments. Runtime .env files
    # are deliberately skipped; .env.example is allowed to contain only placeholder config.
    forbidden_assignments = [
        "GEMINI" + "_API_KEY=",
        "GOOGLE" + "_API_KEY=",
        "OPENAI" + "_API_KEY=",
        "ANTHROPIC" + "_API_KEY=",
        "GRB_" + "WLSACCESSID=",
        "GRB_" + "WLSSECRET=",
        "-----BEGIN " + "PRIVATE KEY-----",
    ]
    for path in root.rglob("*"):
        if not path.is_file() or _is_runtime_or_generated(path, root):
            continue
        if path.name in LOCAL_SECRET_FILES:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for token in forbidden_assignments:
            if token in text and path.name != ".env.example":
                failures.append(f"possible embedded secret/config token: {path}")

    return failures


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    failures = scan_root(root)
    if failures:
        raise SystemExit("\n".join(failures))
    print("STATIC_GATE=PASS")


if __name__ == "__main__":
    main()
