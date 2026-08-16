from __future__ import annotations

from pathlib import Path
import re

from mdt.domain import FactoryModel, JobSpec, MachineSpec, OperationSpec
from mdt.data.validation import validate_factory_model

_INSTANCE_RE = re.compile(r"^\s*instance\s+(\S+)\s*$", re.IGNORECASE)


def parse_orlib_instances(text: str) -> dict[str, tuple[int, int, list[list[int]]]]:
    lines = text.splitlines()
    instances: dict[str, tuple[int, int, list[list[int]]]] = {}
    i = 0
    while i < len(lines):
        match = _INSTANCE_RE.match(lines[i])
        if not match:
            i += 1
            continue
        name = match.group(1).lower()
        i += 1
        while i < len(lines) and not re.match(r"^\s*\d+\s+\d+\s*$", lines[i]):
            if _INSTANCE_RE.match(lines[i]):
                break
            i += 1
        if i >= len(lines) or not re.match(r"^\s*\d+\s+\d+\s*$", lines[i]):
            continue
        n_jobs, n_machines = map(int, lines[i].split())
        rows: list[list[int]] = []
        i += 1
        while i < len(lines) and len(rows) < n_jobs:
            stripped = lines[i].strip()
            if not stripped or stripped.startswith("+"):
                i += 1
                continue
            if _INSTANCE_RE.match(lines[i]):
                break
            parts = stripped.split()
            if all(p.lstrip("-").isdigit() for p in parts) and len(parts) == 2 * n_machines:
                rows.append([int(x) for x in parts])
            i += 1
        if len(rows) == n_jobs:
            instances[name] = (n_jobs, n_machines, rows)
    return instances


def load_orlib_instance(path: str | Path, instance_name: str = "ft06") -> FactoryModel:
    path = Path(path)
    instances = parse_orlib_instances(path.read_text(encoding="utf-8", errors="replace"))
    key = instance_name.lower()
    if key not in instances:
        raise KeyError(f"OR-Library instance '{instance_name}' not found")
    n_jobs, n_machines, rows = instances[key]
    machines = tuple(MachineSpec(f"M{idx}", f"Machine {idx}") for idx in range(n_machines))
    jobs: list[JobSpec] = []
    for j_idx, row in enumerate(rows):
        job_id = f"J{j_idx}"
        operations: list[OperationSpec] = []
        for seq in range(n_machines):
            machine_index = row[2 * seq]
            processing_time = float(row[2 * seq + 1])
            operations.append(
                OperationSpec(
                    operation_id=f"{job_id}-O{seq}",
                    job_id=job_id,
                    sequence=seq,
                    machine_id=f"M{machine_index}",
                    processing_time=processing_time,
                )
            )
        jobs.append(JobSpec(job_id=job_id, operations=tuple(operations), release_time=0.0))
    model = FactoryModel(
        factory_id=f"orlib-{key}",
        machines=machines,
        jobs=tuple(jobs),
        source="OR-Library jobshop1.txt",
        source_kind="public_benchmark",
        metadata={"instance": key, "jobs": n_jobs, "machines": n_machines},
    )
    validate_factory_model(model)
    return model
