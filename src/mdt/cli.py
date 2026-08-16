from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from mdt.config import Settings
from mdt.ie import identify_constraint
from mdt.service import TwinService


def main() -> None:
    parser = argparse.ArgumentParser(prog="mdt")
    parser.add_argument("command", choices=["status", "factory"])
    args = parser.parse_args()
    settings = Settings.from_env(Path.cwd())
    with TwinService(settings) as service:
        if args.command == "factory":
            result = {
                "factory_id": service.model.factory_id,
                "jobs": len(service.model.jobs),
                "machines": len(service.model.machines),
                "operations": service.model.operation_count,
                "total_work": service.model.total_work,
                "constraint": asdict(identify_constraint(service.model)),
            }
        else:
            snapshot = service.engine.snapshot()
            result = {
                "timestamp": snapshot.timestamp,
                "events": snapshot.event_count,
                "wip_jobs": snapshot.wip_jobs,
                "completed_jobs": snapshot.completed_jobs,
                "ready_operations": snapshot.ready_operations,
            }
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
