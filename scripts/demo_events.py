from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

from mdt.config import Settings
from mdt.domain import EventType, ManufacturingEvent
from mdt.service import TwinService


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    with TwinService(Settings.from_env(root)) as service:
        if service.repository.count():
            print(
                json.dumps(
                    {"status": "SKIPPED", "reason": "runtime database already contains events"},
                    indent=2,
                )
            )
            return
        events = [
            ManufacturingEvent(str(uuid4()), EventType.JOB_RELEASED, 0, job_id="J0"),
            ManufacturingEvent(
                str(uuid4()),
                EventType.OPERATION_STARTED,
                0,
                job_id="J0",
                operation_id="J0-O0",
                machine_id="M2",
            ),
            ManufacturingEvent(
                str(uuid4()),
                EventType.OPERATION_COMPLETED,
                1,
                job_id="J0",
                operation_id="J0-O0",
                machine_id="M2",
            ),
        ]
        for event in events:
            service.engine.apply(event)
            service.repository.append(event)
        snapshot = service.engine.snapshot()
        payload = {
            "status": "LOADED",
            "events": snapshot.event_count,
            "ready_operations": snapshot.ready_operations,
            "wip_jobs": snapshot.wip_jobs,
        }
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
