from pathlib import Path

from scripts.fortune50_preflight import build_report


def test_fortune50_prepublication_boundary_is_complete() -> None:
    root = Path(__file__).resolve().parents[1]
    report = build_report(root)
    assert report["status"] == "PASS", report["failures"]
    assert report["synthetic_dataset"] == {
        "rows": 150_000,
        "columns": 80,
        "integrity_ready": True,
    }
