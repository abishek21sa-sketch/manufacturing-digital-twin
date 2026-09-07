"""Fast, offline pre-publication gate for the Fortune-50-style portfolio boundary."""

from __future__ import annotations

import json
from pathlib import Path

from mdt.data.synthetic import synthetic_dataset_summary


REQUIRED_DOCS = (
    "docs/FORTUNE50_READINESS.md",
    "docs/MODEL_CARDS.md",
    "docs/PUBLIC_DATA_CATALOG.md",
    "data/synthetic/DATASET_MANIFEST.json",
    "docs/evidence/AI_VALIDATION.json",
    "docs/evidence/OPERATIONAL_AI_VALIDATION.json",
)


def _has_limitations(value: object) -> bool:
    if isinstance(value, dict):
        if isinstance(value.get("limitations"), str) and value["limitations"].strip():
            return True
        return any(_has_limitations(item) for item in value.values())
    if isinstance(value, list):
        return any(_has_limitations(item) for item in value)
    return False


def build_report(root: Path) -> dict[str, object]:
    failures: list[str] = []
    for relative in REQUIRED_DOCS:
        if not (root / relative).exists():
            failures.append(f"missing required public artifact: {relative}")

    manifest_path = root / "data" / "synthetic" / "DATASET_MANIFEST.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        references = manifest.get("public_references", [])
        if len(references) < 4:
            failures.append("public data catalog has fewer than four documented references")
        for index, reference in enumerate(references):
            for field in ("name", "url", "use", "license"):
                if not str(reference.get(field, "")).strip():
                    failures.append(f"public reference {index} is missing {field}")

    try:
        summary = synthetic_dataset_summary(str(root))
    except Exception as exc:  # pragma: no cover - release gate diagnostic
        failures.append(f"synthetic dataset integrity check failed: {exc}")
        summary = {"integrity": {"ready": False}}
    if not summary.get("integrity", {}).get("ready"):
        failures.append("synthetic dataset is not digest/semantic-ready")
    if summary.get("rows") != 150_000 or summary.get("columns") != 80:
        failures.append("synthetic dataset contract is not 150,000 x 80")

    for relative in ("docs/evidence/AI_VALIDATION.json", "docs/evidence/OPERATIONAL_AI_VALIDATION.json"):
        path = root / relative
        if path.exists():
            evidence = json.loads(path.read_text(encoding="utf-8"))
            if not _has_limitations(evidence):
                failures.append(f"model evidence has no explicit limitations: {relative}")

    readiness_path = root / "docs" / "FORTUNE50_READINESS.md"
    readiness_text = readiness_path.read_text(encoding="utf-8") if readiness_path.exists() else ""
    for token in ("plant deployment", "synthetic", "external", "human"):
        if token.lower() not in readiness_text.lower():
            failures.append(f"readiness boundary missing token: {token}")

    return {
        "status": "PASS" if not failures else "FAIL",
        "gate": "FORTUNE50_PREPUBLICATION_GATE",
        "scope": "public portfolio/research release, not plant deployment approval",
        "synthetic_dataset": {
            "rows": summary.get("rows"),
            "columns": summary.get("columns"),
            "integrity_ready": summary.get("integrity", {}).get("ready", False),
        },
        "failures": failures,
    }


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    report = build_report(root)
    print(json.dumps(report, indent=2))
    if report["status"] != "PASS":
        raise SystemExit("FORTUNE50_PREPUBLICATION_GATE=FAIL")
    print("FORTUNE50_PREPUBLICATION_GATE=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
