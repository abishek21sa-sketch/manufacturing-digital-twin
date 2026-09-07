from __future__ import annotations

import argparse
import json
from pathlib import Path

from mdt.config import Settings


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate production configuration without contacting external plant systems.")
    parser.add_argument("--static", action="store_true", help="Only verify packaged paths and production configuration shape.")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    settings = Settings.from_env(root)
    settings.validate_operational()
    paths = {
        "workspace": (root / "workspace" / "index.html").exists(),
        "benchmark": (root / "data" / "external" / "orlib" / "jobshop1.txt").exists(),
        "model_artifacts": all((root / "artifacts" / "ai" / name).exists() for name in ("lateness_risk.joblib", "cycle_time.joblib", "bottleneck.joblib", "anomaly.joblib")),
        "migration_config": (root / "alembic.ini").exists() and (root / "migrations" / "env.py").exists(),
        "migration_baseline": (root / "migrations" / "versions" / "0001_rc4_hardening.py").exists(),
        "security_policy": (root / "SECURITY.md").exists(),
    }
    if not all(paths.values()):
        raise SystemExit(f"packaged production paths are incomplete: {paths}")
    print(json.dumps({
        "status": "pass",
        "environment": settings.environment,
        "instance_id": settings.instance_id,
        "database_scheme": settings.database_url.split(":", 1)[0],
        "auth_mode": settings.auth_mode,
        "schema_revision": settings.schema_revision,
        "event_contract_version": settings.event_contract_version,
        "static": args.static,
        "paths": paths,
    }, indent=2))
    print("MDT_PRODUCTION_PREFLIGHT=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
