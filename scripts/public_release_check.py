from __future__ import annotations

import json
import re
from pathlib import Path

from mdt import __version__

REQUIRED = (
    "README.md", "LICENSE", ".gitignore", ".env.example", ".gitattributes",
    ".github/workflows/windows-ci.yml",
    "docs/ARCHITECTURE.md", "docs/TECHNICAL_METHODS.md", "docs/VALIDATION.md",
    "docs/VALIDATION_EVIDENCE.json", "docs/CONSTITUTION_TRACEABILITY.md",
    "docs/CONSTITUTION_TRACEABILITY.json", "docs/DATA.md", "docs/DATA_DICTIONARY.md",
    "docs/WINDOWS_DEPLOYMENT.md", "docs/QUALITY_GATE.md", "docs/FUTURE_WORK.md",
    "docs/RELEASE_NOTES.md", "docs/METHODOLOGY.md", "workspace/methodology.html", "workspace/methodology.js",
    "accept_v1_windows.bat", "requirements-windows-tested.txt",
    "run_windows.bat", "scripts/windows_preflight.py",
)

OBSOLETE = (
    # Root-level development/phase acceptance artifacts.  These are checked
    # *before* the expensive suite so an over-extracted old working directory
    # cannot waste another full Windows acceptance cycle.
    "accept_constitution_closure_windows.bat",
    "accept_phase1_windows.bat",
    "accept_phase2_windows.bat",
    "accept_phase3_windows.bat",
    "accept_phase4_windows.bat",
    "retest_constitution_pareto_windows.bat",
    "retest_constitution_patch_windows.bat",
    "retest_solver_contract_windows.bat",
    "retest_workspace_launch_windows.bat",
    "run_unix.sh",
    # Candidate/phase Python gates superseded by the final V1 path.
    "scripts/constitution_closure_diagnostics.py",
    "scripts/constitution_release_check.py",
    "scripts/constitution_windows_acceptance.py",
    "scripts/diagnostics.py",
    "scripts/phase3_windows_acceptance.py",
    "scripts/phase4_windows_acceptance.py",
    "scripts/windows_product_acceptance.py",
    # Historical phase evidence intentionally consolidated into the V1 docs.
    "docs/CONSTITUTION_CLOSURE_EVIDENCE.json",
    "docs/IE_METHODS_PHASE1.md",
    "docs/PHASE1_ACCEPTANCE.md",
    "docs/PHASE1_IMPLEMENTATION_MATRIX.md",
    "docs/PHASE1_RELEASE_NOTES.md",
    "docs/PHASE1_VALIDATION_EVIDENCE.json",
    "docs/PHASE2_ACCEPTANCE.md",
    "docs/PHASE2_AI_VALIDATION.json",
    "docs/PHASE2_METHODS.md",
    "docs/PHASE2_RELEASE_NOTES.md",
    "docs/PHASE2_VALIDATION_EVIDENCE.json",
    "docs/PHASE3_ACCEPTANCE.md",
    "docs/PHASE3_METHODS.md",
    "docs/PHASE3_RELEASE_NOTES.md",
    "docs/PHASE3_VALIDATION_EVIDENCE.json",
    "docs/PHASE4_ACCEPTANCE.md",
    "docs/PHASE4_ARCHITECTURE_DECISIONS.md",
    "docs/PHASE4_METHODS.md",
    "docs/PHASE4_RELEASE_NOTES.md",
    "docs/PHASE4_VALIDATION_EVIDENCE.json",
    "docs/governance/FINALIZATION_PROTOCOL.txt",
)

BAD_TREE_PARTS = {".venv", ".git", "__pycache__", ".pytest_cache", "runtime"}
BAD_SUFFIXES = {".pyc", ".pyo", ".log", ".zip"}


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    failures: list[str] = []
    if __version__ != "1.0.0":
        failures.append(f"package version is {__version__}, expected 1.0.0")
    pyproject = (root / "pyproject.toml").read_text(encoding="utf-8")
    if 'version = "1.0.0"' not in pyproject:
        failures.append("pyproject version is not 1.0.0")
    for rel in REQUIRED:
        if not (root / rel).exists():
            failures.append(f"missing public release artifact: {rel}")
    for rel in OBSOLETE:
        if (root / rel).exists():
            failures.append(f"obsolete candidate/retest artifact remains: {rel}")

    readme = (root / "README.md").read_text(encoding="utf-8")
    required_story = ("synchronized", "Gurobi", "Industrial Engineering", "stochastic", "human", "limitations", "V1.0", "1.0.0")
    for token in required_story:
        if token.lower() not in readme.lower():
            failures.append(f"README engineering story missing token: {token}")
    if re.search(r"Phase 5A|Constitution-Closure Candidate|Remaining before V1", readme, re.I):
        failures.append("README still contains pre-final candidate framing")

    trace = json.loads((root / "docs" / "CONSTITUTION_TRACEABILITY.json").read_text(encoding="utf-8"))
    allowed = set(trace.get("allowed_statuses", []))
    if trace.get("release") != "V1.0" or trace.get("version") != "1.0.0":
        failures.append("Constitution traceability release/version mismatch")
    if trace.get("unresolved"):
        failures.append(f"Constitution traceability unresolved items: {trace['unresolved']}")
    if len(trace.get("requirements", [])) < 60:
        failures.append("Constitution traceability is unexpectedly incomplete")
    bad_status = [row for row in trace.get("requirements", []) if row.get("status") not in allowed]
    if bad_status:
        failures.append("Constitution traceability contains unapproved status values")

    quality = (root / "docs" / "QUALITY_GATE.md").read_text(encoding="utf-8")
    if "25 / 25 resolved for V1.0" not in quality:
        failures.append("final 25-question quality gate is not fully resolved")

    ui = (root / "workspace" / "index.html").read_text(encoding="utf-8")
    js = (root / "workspace" / "app.js").read_text(encoding="utf-8")
    methodology = (root / "workspace" / "methodology.html").read_text(encoding="utf-8")
    for token in ("MANUFACTURING DIGITAL TWIN · V1.0", "DECISION EVIDENCE PACKET", "twinStateId", "decisionDisposition", "HUMAN DECISION GATE"):
        if token not in ui:
            failures.append(f"final workspace missing: {token}")
    for token in ("/v1/decisions/", "renderDecisionPacket", "data-disposition", "/v1/ai/operational", "/v1/ie/control-plan"):
        if token not in js and token not in ui:
            failures.append(f"final workspace contract missing: {token}")
    for token in ("Engineering Methodology", "LITTLE'S LAW", "NO-REGRET SERVICE GUARD", "SCENARIO-BASED CVaR POLICY MILP"):
        if token not in methodology:
            failures.append(f"final methodology page missing: {token}")

    ignore_lines = {line.strip() for line in (root / ".gitignore").read_text(encoding="utf-8").splitlines() if line.strip() and not line.startswith("#")}
    if ".env" not in ignore_lines:
        failures.append(".gitignore must explicitly ignore .env")
    if (root / ".env").exists():
        # Local .env is allowed during acceptance but is never source material.
        pass

    run_bat = (root / "run_windows.bat").read_text(encoding="utf-8").lower()
    if "public_release_check" in run_bat or "release_check.py" in run_bat:
        failures.append("runtime launcher is incorrectly coupled to release acceptance")

    for path in root.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(root)
        if any(part in BAD_TREE_PARTS for part in rel.parts):
            continue
        if path.suffix.lower() in BAD_SUFFIXES:
            # Test/compile runs legitimately create cache/log files; packaging excludes them.
            continue
        if path.name == ".env":
            # allowed only as local, untracked runtime config; packaging gate excludes it.
            continue
        if path.suffix.lower() in {".db", ".sqlite", ".sqlite3"}:
            failures.append(f"public tree contains runtime database: {rel}")

    if failures:
        raise SystemExit("\n".join(failures))
    print("PUBLIC_RELEASE_CHECK=PASS")


if __name__ == "__main__":
    main()
