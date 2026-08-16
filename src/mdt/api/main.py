from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import asdict
from importlib.util import find_spec
import json
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from mdt import __version__
from mdt.ai import (
    load_anomaly,
    load_bottleneck,
    load_bundle,
    load_cycle_time,
    score_cycle_time,
    score_bottleneck,
    score_planning_jobs,
    score_snapshot_anomalies,
)
from mdt.config import Settings
from mdt.copilot import GeminiCopilot, GeminiUnavailable
from mdt.data import CANONICAL_EVENT_COLUMNS, inspect_event_csv, replay_events
from mdt.decision import build_twin_future_state_stress_test, build_twin_recovery_decision
from mdt.domain import EventType, HumanDisposition, ManufacturingEvent
from mdt.ie import (
    capacity_plan,
    conwip_release_allowed,
    drum_buffer_rope_plan,
    identify_constraint,
    individuals_mr,
    oee,
    process_cycle_efficiency,
    takt_time,
)
from mdt.optimization import (
    GurobiUnavailable,
    ObjectiveWeights,
    ScheduleProblem,
    default_planning_jobs,
    gurobi_available,
    solve_schedule,
    assess_schedule,
    validate_schedule,
)
from mdt.planning import PlanningStateNotReady, planning_state_from_twin
from mdt.service import TwinService
from mdt.simulation import PolicySpec, ReliabilitySpec, SimulationConfig, simulate, validate_simulation
from mdt.twin import TwinStateError


def _root() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "pyproject.toml").exists():
            return parent
    return Path.cwd()


class EventIn(BaseModel):
    event_id: str | None = None
    event_type: EventType
    timestamp: float = Field(ge=0)
    job_id: str | None = None
    operation_id: str | None = None
    machine_id: str | None = None
    payload: dict = Field(default_factory=dict)


class ScheduleIn(BaseModel):
    backend: str = "auto"
    due_factor: float = Field(default=1.5, gt=0)
    makespan_weight: float = Field(default=0.05, ge=0)
    tardiness_weight: float = Field(default=1.0, ge=0)
    risk_tardiness_weight: float = Field(default=2.0, ge=0)
    use_ai_risk: bool = True
    time_limit_seconds: float = Field(default=30.0, gt=0, le=300)
    down_machine_recovery: dict[str, float] = Field(default_factory=dict)


class RecoveryIn(BaseModel):
    backend: str = "auto"
    due_factor: float = Field(default=1.5, gt=0)
    time_limit_seconds: float = Field(default=30.0, gt=0, le=300)
    processing_cv: float = Field(default=0.10, ge=0, le=1.0)
    mtbf: float | None = Field(default=120.0, gt=0)
    mttr: float = Field(default=8.0, gt=0)
    down_machine_recovery: dict[str, float] = Field(default_factory=dict)


class SimulationIn(BaseModel):
    policy: str = "SPT"
    backend: str = "auto"
    due_factor: float = Field(default=1.5, gt=0)
    seed: int = 20260815
    processing_cv: float = Field(default=0.10, ge=0, le=1.0)
    mtbf: float | None = Field(default=120.0, gt=0)
    mttr: float = Field(default=8.0, gt=0)
    stressed_machine_id: str | None = None
    stressed_machine_mtbf: float | None = Field(default=None, gt=0)
    stressed_machine_mttr: float | None = Field(default=None, gt=0)
    time_limit_seconds: float = Field(default=30.0, gt=0, le=300)
    include_events: bool = False
    wip_cap: int | None = Field(default=None, gt=0)
    down_machine_recovery: dict[str, float] = Field(default_factory=dict)


class StressTestIn(BaseModel):
    backend: str = "auto"
    due_factor: float = Field(default=1.5, gt=0)
    time_limit_seconds: float = Field(default=30.0, gt=0, le=300)
    replications: int = Field(default=60, ge=2, le=500)
    base_seed: int = 20260815
    processing_cv: float = Field(default=0.10, ge=0, le=1.0)
    mtbf: float | None = Field(default=120.0, gt=0)
    mttr: float = Field(default=8.0, gt=0)
    risk_aversion: float = Field(default=0.35, ge=0, le=5.0)
    stressed_machine_id: str | None = None
    stressed_machine_mtbf: float | None = Field(default=None, gt=0)
    stressed_machine_mttr: float | None = Field(default=None, gt=0)
    wip_cap: int | None = Field(default=None, gt=0)
    down_machine_recovery: dict[str, float] = Field(default_factory=dict)


class DispositionIn(BaseModel):
    disposition: HumanDisposition
    note: str | None = Field(default=None, max_length=2000)


class EventCsvIn(BaseModel):
    csv_text: str = Field(min_length=1, max_length=2_000_000)


class CopilotScenarioIn(BaseModel):
    request: str = Field(min_length=3, max_length=3000)
    backend: str = "auto"
    time_limit_seconds: float = Field(default=30.0, gt=0, le=300)
    base_seed: int = 20260815


class CopilotExplainIn(BaseModel):
    question: str = Field(min_length=3, max_length=3000)
    backend: str = "auto"
    due_factor: float = Field(default=1.5, gt=0)
    replications: int = Field(default=12, ge=4, le=100)
    base_seed: int = 20260815
    processing_cv: float = Field(default=0.10, ge=0, le=0.75)
    mtbf: float | None = Field(default=120.0, gt=0)
    mttr: float = Field(default=8.0, gt=0)
    risk_aversion: float = Field(default=0.35, ge=0, le=3.0)
    stressed_machine_id: str | None = None
    stressed_machine_mtbf: float | None = Field(default=None, gt=0)
    stressed_machine_mttr: float | None = Field(default=None, gt=0)


def snapshot_payload(service: TwinService) -> dict:
    s = service.engine.snapshot()
    return {
        "timestamp": s.timestamp,
        "event_count": s.event_count,
        "wip_jobs": s.wip_jobs,
        "completed_jobs": s.completed_jobs,
        "ready_operations": s.ready_operations,
        "machines": {k: asdict(v) for k, v in s.machines.items()},
        "jobs": {k: asdict(v) for k, v in s.jobs.items()},
        "operations": {k: asdict(v) for k, v in s.operations.items()},
    }


def _machine_overrides(model, machine_id: str | None, mtbf: float | None, mttr: float | None, default_mtbf: float | None, default_mttr: float) -> dict[str, ReliabilitySpec]:
    if machine_id is None:
        return {}
    known = {m.machine_id for m in model.machines}
    if machine_id not in known:
        raise ValueError(f"unknown stressed_machine_id {machine_id}")
    return {
        machine_id: ReliabilitySpec(
            mtbf=mtbf if mtbf is not None else default_mtbf,
            mttr=mttr if mttr is not None else default_mttr,
        )
    }


def _copilot(settings: Settings) -> GeminiCopilot:
    if not settings.copilot_enabled:
        raise GeminiUnavailable("Gemini copilot is disabled by MDT_COPILOT_ENABLED")
    return GeminiCopilot(settings.gemini_api_key, settings.gemini_model)


def _copilot_evidence(stress: dict, factory_payload: dict) -> dict:
    summaries = stress.get("stress_test", {}).get("summaries", [])
    return {
        "factory": factory_payload,
        "evidence_labels": stress.get("evidence_labels", {}),
        "planning_state": stress.get("planning_state", {}),
        "ai": stress.get("ai", {}),
        "nominal_solver": stress.get("nominal_optimized", {}).get("solver", {}),
        "nominal_schedule": {
            "makespan": stress.get("nominal_optimized", {}).get("makespan"),
            "total_tardiness": stress.get("nominal_optimized", {}).get("total_tardiness"),
        },
        "robust_schedule": {
            "makespan": stress.get("robust_optimized", {}).get("makespan"),
            "total_tardiness": stress.get("robust_optimized", {}).get("total_tardiness"),
            "uncertainty": stress.get("robust_optimized", {}).get("uncertainty"),
        },
        "policy_summaries": [
            {
                "policy": row.get("policy"),
                "mean_makespan": row.get("mean_makespan"),
                "mean_total_tardiness": row.get("mean_total_tardiness"),
                "cvar95_total_tardiness": row.get("cvar95_total_tardiness"),
                "mean_service_level": row.get("mean_service_level"),
                "robust_score": row.get("robust_score"),
            }
            for row in summaries
        ],
        "recommended_policy": stress.get("stress_test", {}).get("recommended_policy"),
        "recommendation_rationale": stress.get("stress_test", {}).get("rationale"),
        "decision_contract": stress.get("decision", {}),
        "limitations": ["benchmark/synthetic/simulated evidence; external plant validation pending"],
    }


def create_app(app_settings: Settings | None = None) -> FastAPI:
    resolved_settings = app_settings or Settings.from_env(_root())

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        service = TwinService(resolved_settings)
        artifact_dir = resolved_settings.project_root / "artifacts" / "ai"
        risk_model = load_bundle(artifact_dir / "lateness_risk.joblib")
        cycle_model = load_cycle_time(artifact_dir / "cycle_time.joblib")
        bottleneck_model = load_bottleneck(artifact_dir / "bottleneck.joblib")
        anomaly_model = load_anomaly(artifact_dir / "anomaly.joblib")
        app.state.service = service
        app.state.risk_model = risk_model
        app.state.cycle_model = cycle_model
        app.state.bottleneck_model = bottleneck_model
        app.state.anomaly_model = anomaly_model
        try:
            yield
        finally:
            service.close()

    application = FastAPI(title="Manufacturing Digital Twin", version=__version__, lifespan=lifespan)
    workspace_dir = resolved_settings.project_root / "workspace"
    if workspace_dir.exists():
        application.mount("/workspace/assets", StaticFiles(directory=workspace_dir), name="workspace-assets")

    def get_service(request: Request) -> TwinService:
        return request.app.state.service

    @application.get("/", include_in_schema=False)
    def root_redirect():
        return RedirectResponse(url="/workspace")

    @application.get("/workspace", include_in_schema=False)
    def workspace():
        index = workspace_dir / "index.html"
        if not index.exists():
            raise HTTPException(status_code=404, detail="workspace frontend is not packaged")
        return FileResponse(index)

    @application.get("/methodology", include_in_schema=False)
    def methodology():
        page = workspace_dir / "methodology.html"
        if not page.exists():
            raise HTTPException(status_code=404, detail="methodology frontend is not packaged")
        return FileResponse(page)

    @application.get("/health")
    def health():
        sdk_available = False
        try:
            sdk_available = find_spec("google.genai") is not None
        except (ImportError, ModuleNotFoundError, ValueError):
            pass
        return {
            "status": "ok",
            "version": __version__,
            "release": "V1.0",
            "gurobi_python_available": gurobi_available(),
            "gemini_sdk_available": sdk_available,
            "gemini_key_configured": bool(resolved_settings.gemini_api_key),
        }

    @application.get("/v1/methodology/evidence")
    def methodology_evidence(request: Request):
        service = get_service(request)
        evidence_dir = resolved_settings.project_root / "docs" / "evidence"
        try:
            lateness = json.loads((evidence_dir / "AI_VALIDATION.json").read_text(encoding="utf-8"))
            operational = json.loads((evidence_dir / "OPERATIONAL_AI_VALIDATION.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise HTTPException(status_code=500, detail="packaged methodology evidence is unavailable") from exc
        return {
            "version": __version__,
            "release": "V1.0",
            "evidence_policy": "benchmark/synthetic/simulated results are not real plant outcomes",
            "benchmark": {
                "instance": service.model.metadata.get("instance", "unknown"),
                "jobs": len(service.model.jobs),
                "machines": len(service.model.machines),
                "operations": service.model.operation_count,
                "total_work": service.model.total_work,
            },
            "ai": {
                "lateness": {"production_model": lateness["production_model"], "baseline": lateness["class_prior_baseline"], "label": lateness["evidence_label"]},
                "cycle_time": {"production_model": operational["cycle_time"]["production_model"], "baseline": operational["cycle_time"]["touch_time_baseline"], "label": operational["cycle_time"]["evidence_label"]},
                "bottleneck": {"production_model": operational["bottleneck"]["production_model"], "baseline": operational["bottleneck"]["static_workload_baseline"], "label": operational["bottleneck"]["evidence_label"]},
                "anomaly": {"production_model": operational["anomaly"]["production_model"], "baseline": operational["anomaly"]["downtime_threshold_baseline"], "label": operational["anomaly"]["evidence_label"]},
            },
            "industrial_engineering": ["Little's Law", "Kingman G/G/1", "TOC", "DBR", "CONWIP", "takt/JIT", "capacity planning", "OEE/PCE", "reliability", "SPC I-MR", "2^k DOE"],
            "operations_research": ["finite-capacity job-shop MILP", "no-regret tardiness guard", "box-robust scheduling", "three-objective Pareto analysis", "scenario-based CVaR policy MILP", "simulation optimization"],
            "simulation": ["discrete-event simulation", "stochastic processing", "machine failure/repair", "preempt-resume", "Monte Carlo", "common random numbers", "CVaR95"],
        }

    @application.get("/v1/factory")
    def factory(request: Request):
        service = get_service(request)
        model = service.model
        constraint = identify_constraint(model)
        return {
            "factory_id": model.factory_id,
            "source": model.source,
            "source_kind": model.source_kind,
            "jobs": len(model.jobs),
            "machines": len(model.machines),
            "operations": model.operation_count,
            "total_work": model.total_work,
            "constraint": asdict(constraint),
            "machine_ids": [m.machine_id for m in model.machines],
        }

    @application.get("/v1/twin/state")
    def twin_state(request: Request):
        return snapshot_payload(get_service(request))

    @application.get("/v1/twin/events")
    def twin_events(request: Request):
        return [asdict(e) for e in get_service(request).repository.list_events()]

    @application.post("/v1/twin/events")
    def append_event(body: EventIn, request: Request):
        service = get_service(request)
        event = ManufacturingEvent(
            body.event_id or str(uuid4()),
            body.event_type,
            body.timestamp,
            body.job_id,
            body.operation_id,
            body.machine_id,
            body.payload,
        )
        try:
            service.engine.apply(event)
            service.repository.append(event)
        except Exception as exc:
            service.refresh()
            if isinstance(exc, TwinStateError):
                raise HTTPException(status_code=409, detail=str(exc)) from exc
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"event": asdict(event), "state": snapshot_payload(service)}

    @application.get("/v1/ai/lateness-risk")
    def lateness_risk(request: Request, due_factor: float = 1.5):
        if due_factor <= 0:
            raise HTTPException(status_code=422, detail="due_factor must be positive")
        service = get_service(request)
        try:
            state = planning_state_from_twin(service.model, service.engine.snapshot(), due_factor=due_factor)
        except PlanningStateNotReady as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        if not state.planning_jobs:
            return {"evidence_label": "PREDICTED — SYNTHETICALLY VALIDATED", "model": request.app.state.risk_model.metadata, "jobs": []}
        scored = score_planning_jobs(request.app.state.risk_model, state.residual_factory, state.planning_jobs)
        return {
            "evidence_label": "PREDICTED — SYNTHETICALLY VALIDATED",
            "model": request.app.state.risk_model.metadata,
            "jobs": [asdict(job) for job in scored],
            "twin_state_id": state.source_state_id,
        }

    @application.get("/v1/ai/operational")
    def operational_ai(
        request: Request,
        due_factor: float = 1.5,
        processing_cv: float = 0.10,
        mtbf: float | None = 120.0,
        mttr: float = 8.0,
    ):
        if due_factor <= 0 or processing_cv < 0 or processing_cv > 1 or (mtbf is not None and mtbf <= 0) or mttr <= 0:
            raise HTTPException(status_code=422, detail="invalid operational AI scenario parameters")
        service = get_service(request)
        snapshot = service.engine.snapshot()
        try:
            state = planning_state_from_twin(service.model, snapshot, due_factor=due_factor)
        except PlanningStateNotReady as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        anomalies = score_snapshot_anomalies(request.app.state.anomaly_model, service.model, snapshot)
        bottleneck = score_bottleneck(
            request.app.state.bottleneck_model,
            state.residual_factory if state.planning_jobs else service.model,
            SimulationConfig(processing_cv=processing_cv, reliability=ReliabilitySpec(mtbf=mtbf, mttr=mttr), record_events=False),
        )
        if not state.planning_jobs:
            return {
                "twin_state_id": state.source_state_id,
                "cycle_time": {},
                "future_bottleneck_probability": bottleneck,
                "machine_anomaly": anomalies,
                "status": "NO_RESIDUAL_WORK",
            }
        scored = score_planning_jobs(request.app.state.risk_model, state.residual_factory, state.planning_jobs)
        cycle = score_cycle_time(request.app.state.cycle_model, state.residual_factory, scored)
        return {
            "evidence_labels": {
                "cycle_time": "PREDICTED — SYNTHETICALLY VALIDATED",
                "bottleneck": "PREDICTED — SYNTHETICALLY VALIDATED",
                "anomaly": "ANOMALY SCORE — NOT A PROBABILITY",
            },
            "twin_state_id": state.source_state_id,
            "cycle_time": cycle,
            "future_bottleneck_probability": bottleneck,
            "machine_anomaly": anomalies,
        }

    @application.get("/v1/ie/control-plan")
    def ie_control_plan(request: Request, due_factor: float = 1.5, horizon: float = 100.0, buffer_time: float = 5.0, wip_limit: int = 3):
        if due_factor <= 0 or horizon <= 0 or buffer_time < 0 or wip_limit <= 0:
            raise HTTPException(status_code=422, detail="invalid IE control parameters")
        service = get_service(request)
        snapshot = service.engine.snapshot()
        try:
            state = planning_state_from_twin(service.model, snapshot, due_factor=due_factor)
        except PlanningStateNotReady as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        factory = state.residual_factory if state.planning_jobs else service.model
        planning_jobs = state.planning_jobs if state.planning_jobs else default_planning_jobs(factory, due_factor)
        cap = capacity_plan(factory, horizon=horizon)
        dbr = drum_buffer_rope_plan(factory, tuple(planning_jobs), buffer_time=buffer_time) if planning_jobs else None
        constraint = identify_constraint(factory)
        return {
            "evidence_label": "CALCULATED INDUSTRIAL ENGINEERING CONTROL PLAN",
            "twin_state_id": state.source_state_id,
            "current_wip_jobs": snapshot.wip_jobs,
            "conwip": {
                "wip_limit": wip_limit,
                "release_allowed": conwip_release_allowed(snapshot.wip_jobs, wip_limit),
            },
            "constraint": asdict(constraint),
            "capacity": [asdict(row) for row in cap],
            "drum_buffer_rope": None if dbr is None else {
                "constraint_machine_id": dbr.constraint_machine_id,
                "buffer_time": dbr.buffer_time,
                "jobs": [asdict(row) for row in dbr.jobs],
            },
            "signal_readiness": {
                "oee": "NOT_AVAILABLE_WITHOUT_QUALITY_AND_IDEAL_CYCLE_SIGNALS",
                "spc": "NOT_AVAILABLE_WITHOUT_REPEATED_OBSERVED_CYCLE_MEASUREMENTS",
                "takt": "NOT_AVAILABLE_WITHOUT_CUSTOMER_DEMAND_INPUT",
            },
        }

    @application.post("/v1/optimization/schedule")
    def optimize_schedule(body: ScheduleIn, request: Request):
        service = get_service(request)
        try:
            state = planning_state_from_twin(
                service.model,
                service.engine.snapshot(),
                due_factor=body.due_factor,
                down_machine_recovery=body.down_machine_recovery,
            )
        except PlanningStateNotReady as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        if not state.planning_jobs:
            return {"evidence_label": "OPTIMIZED DECISION", "status": "NO_RESIDUAL_WORK", "operations": [], "violations": []}
        jobs = state.planning_jobs
        if body.use_ai_risk:
            jobs = score_planning_jobs(request.app.state.risk_model, state.residual_factory, jobs)
        problem = ScheduleProblem(
            state.residual_factory,
            jobs,
            ObjectiveWeights(body.makespan_weight, body.tardiness_weight, body.risk_tardiness_weight),
            current_time=state.current_time,
            machine_available_from=state.machine_available_from,
        )
        try:
            result = solve_schedule(problem, body.backend, body.time_limit_seconds, 0.0)
        except GurobiUnavailable as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        violations = validate_schedule(problem, result)
        return {
            "evidence_label": "OPTIMIZED DECISION",
            "solver": asdict(result.evidence),
            "makespan": result.makespan,
            "job_tardiness": result.job_tardiness,
            "objective_components": result.objective_components,
            "violations": [asdict(v) for v in violations],
            "operations": [asdict(op) for op in result.operations],
            "twin_state_id": state.source_state_id,
            "frozen_operations": [asdict(op) for op in state.frozen_operations],
        }

    @application.post("/v1/decision/recovery")
    def recovery(body: RecoveryIn, request: Request):
        service = get_service(request)
        try:
            result = build_twin_recovery_decision(
                service.model,
                service.engine.snapshot(),
                request.app.state.risk_model,
                request.app.state.cycle_model,
                request.app.state.bottleneck_model,
                request.app.state.anomaly_model,
                backend=body.backend,
                due_factor=body.due_factor,
                time_limit=body.time_limit_seconds,
                processing_cv=body.processing_cv,
                mtbf=body.mtbf,
                mttr=body.mttr,
                down_machine_recovery=body.down_machine_recovery,
            )
            planning = result.get("planning_state", {})
            solver_backend = result.get("nominal_optimized", {}).get("solver", {}).get("backend", body.backend)
            service.repository.save_decision_run(
                run_id=result["run_id"],
                decision_kind="recovery",
                twin_state_id=planning.get("twin_state_id", "unknown"),
                twin_timestamp=float(planning.get("twin_timestamp", service.engine.snapshot().timestamp)),
                twin_event_count=int(planning.get("twin_event_count", service.engine.snapshot().event_count)),
                model_version=__version__,
                solver_backend=str(solver_backend),
                data_version=f"{service.model.metadata.get('instance', 'unknown')}:{service.model.source_kind}",
                request_payload=body.model_dump(),
                result_payload=result,
                status=result.get("decision", {}).get("recommended_schedule", "NO_ACTION"),
            )
            return result
        except GurobiUnavailable as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except PlanningStateNotReady as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @application.post("/v1/simulation/run")
    def run_simulation(body: SimulationIn, request: Request):
        service = get_service(request)
        try:
            state = planning_state_from_twin(
                service.model,
                service.engine.snapshot(),
                due_factor=body.due_factor,
                down_machine_recovery=body.down_machine_recovery,
            )
        except PlanningStateNotReady as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        if not state.planning_jobs:
            return {"evidence_label": "SIMULATED FUTURE STATE", "status": "NO_RESIDUAL_WORK", "operations": [], "violations": []}
        jobs = score_planning_jobs(request.app.state.risk_model, state.residual_factory, state.planning_jobs)
        problem = ScheduleProblem(
            state.residual_factory,
            jobs,
            ObjectiveWeights(makespan=0.05, tardiness=1.0, risk_tardiness=2.0),
            current_time=state.current_time,
            machine_available_from=state.machine_available_from,
        )
        policy_key = body.policy.upper()
        if policy_key == "OPTIMIZED":
            try:
                nominal = solve_schedule(problem, body.backend, body.time_limit_seconds, 0.0)
            except GurobiUnavailable as exc:
                raise HTTPException(status_code=503, detail=str(exc)) from exc
            nominal_assessment = assess_schedule(problem, nominal)
            nominal_violations = nominal_assessment.violations
            if not nominal_assessment.feasible:
                raise HTTPException(status_code=409, detail="nominal optimized schedule has no complete feasible incumbent")
            policy = PolicySpec("AI_RISK_OPTIMIZED", "PLANNED", {op.operation_id: op.start for op in nominal.operations})
        elif policy_key in {"SPT", "EDD", "FIFO"}:
            policy = PolicySpec(f"{policy_key}_DISPATCH", policy_key)
        else:
            raise HTTPException(status_code=422, detail="policy must be SPT, EDD, FIFO, or OPTIMIZED")
        try:
            overrides = _machine_overrides(
                state.residual_factory,
                body.stressed_machine_id,
                body.stressed_machine_mtbf,
                body.stressed_machine_mttr,
                body.mtbf,
                body.mttr,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        config = SimulationConfig(
            seed=body.seed,
            processing_cv=body.processing_cv,
            reliability=ReliabilitySpec(mtbf=body.mtbf, mttr=body.mttr),
            machine_reliability=overrides,
            wip_cap=body.wip_cap,
            record_events=body.include_events,
        )
        result = simulate(problem, policy, config)
        violations = validate_simulation(problem, result)
        return {
            "evidence_label": "SIMULATED FUTURE STATE — SYNTHETIC/BENCHMARK INPUTS",
            "policy": result.policy,
            "seed": result.seed,
            "metrics": asdict(result.metrics),
            "job_tardiness": result.job_tardiness,
            "machine_downtime": result.machine_downtime,
            "failures": len(result.downtime_intervals),
            "violations": [asdict(v) for v in violations],
            "operations": [asdict(op) for op in result.operations],
            "downtime_intervals": [asdict(interval) for interval in result.downtime_intervals],
            "events": [asdict(event) for event in result.events] if body.include_events else [],
            "twin_state_id": state.source_state_id,
            "frozen_operations": [asdict(op) for op in state.frozen_operations],
        }

    @application.post("/v1/decision/stress-test")
    def stress_test(body: StressTestIn, request: Request):
        service = get_service(request)
        try:
            result = build_twin_future_state_stress_test(
                service.model,
                service.engine.snapshot(),
                request.app.state.risk_model,
                request.app.state.cycle_model,
                request.app.state.bottleneck_model,
                request.app.state.anomaly_model,
                backend=body.backend,
                due_factor=body.due_factor,
                time_limit=body.time_limit_seconds,
                replications=body.replications,
                base_seed=body.base_seed,
                processing_cv=body.processing_cv,
                mtbf=body.mtbf,
                mttr=body.mttr,
                risk_aversion=body.risk_aversion,
                stressed_machine_id=body.stressed_machine_id,
                stressed_machine_mtbf=body.stressed_machine_mtbf,
                stressed_machine_mttr=body.stressed_machine_mttr,
                down_machine_recovery=body.down_machine_recovery,
                wip_cap=body.wip_cap,
            )
            planning = result.get("planning_state", {})
            solver_backend = result.get("nominal_optimized", {}).get("solver", {}).get("backend", body.backend)
            service.repository.save_decision_run(
                run_id=result["run_id"],
                decision_kind="future_state_stress_test",
                twin_state_id=planning.get("twin_state_id", "unknown"),
                twin_timestamp=float(planning.get("twin_timestamp", service.engine.snapshot().timestamp)),
                twin_event_count=int(planning.get("twin_event_count", service.engine.snapshot().event_count)),
                model_version=__version__,
                solver_backend=str(solver_backend),
                data_version=f"{service.model.metadata.get('instance', 'unknown')}:{service.model.source_kind}",
                request_payload=body.model_dump(),
                result_payload=result,
                status=result.get("stress_test", {}).get("recommended_policy", "NO_ACTION"),
            )
            return result
        except GurobiUnavailable as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except PlanningStateNotReady as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @application.get("/v1/decisions")
    def decision_runs(request: Request, limit: int = 50):
        try:
            return get_service(request).repository.list_decision_runs(limit=limit)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @application.post("/v1/decisions/{run_id}/disposition")
    def decision_disposition(run_id: str, body: DispositionIn, request: Request):
        try:
            return get_service(request).repository.update_decision_disposition(run_id, body.disposition, body.note)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=f"decision run not found: {run_id}") from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @application.get("/v1/data/readiness")
    def data_readiness():
        return {
            "evidence_label": "EXTERNAL DATA READINESS",
            "supported_modes": ["PUBLIC_BENCHMARK", "CANONICAL_CSV_HISTORICAL_REPLAY"],
            "live_stream_status": "EXTERNAL VALIDATION PENDING",
            "canonical_event_columns": list(CANONICAL_EVENT_COLUMNS),
            "sample_file": "data/samples/historical_events.csv",
            "commit_policy": "uploaded CSV is validated and replayed in an isolated twin; it is never silently committed to the live event ledger",
        }

    @application.post("/v1/data/validate-events")
    def validate_events(body: EventCsvIn, request: Request):
        report, events = inspect_event_csv(body.csv_text, get_service(request).model)
        return {
            "evidence_label": "CALCULATED DATA READINESS",
            "report": report.to_dict(),
            "events": [asdict(event) for event in events] if report.ready else [],
        }

    @application.post("/v1/data/replay-events")
    def replay_uploaded_events(body: EventCsvIn, request: Request):
        report, events = inspect_event_csv(body.csv_text, get_service(request).model)
        if not report.ready:
            raise HTTPException(status_code=422, detail=report.to_dict())
        return {
            "evidence_label": "HISTORICAL REPLAY — USER-SUPPLIED CANONICAL EVENTS",
            "report": report.to_dict(),
            "state": replay_events(get_service(request).model, events),
            "persisted": False,
        }

    @application.get("/v1/copilot/status")
    def copilot_status():
        sdk = False
        try:
            sdk = find_spec("google.genai") is not None
        except (ImportError, ModuleNotFoundError, ValueError):
            pass
        return {
            "provider": "Google Gemini",
            "model": resolved_settings.gemini_model,
            "enabled": resolved_settings.copilot_enabled,
            "api_key_configured": bool(resolved_settings.gemini_api_key),
            "sdk_available": sdk,
            "role": "scenario interpretation and evidence-grounded explanation only; engineering math remains deterministic",
        }

    @application.post("/v1/copilot/interpret-scenario")
    def interpret_scenario(body: CopilotScenarioIn):
        try:
            intent = _copilot(resolved_settings).interpret_scenario(body.request)
        except GeminiUnavailable as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return {
            "evidence_label": "LLM-INTERPRETED INPUT — NOT AN ENGINEERING RESULT",
            "provider": "Google Gemini",
            "model": resolved_settings.gemini_model,
            "intent": intent.model_dump(),
        }

    @application.post("/v1/copilot/run-scenario")
    def run_copilot_scenario(body: CopilotScenarioIn, request: Request):
        service = get_service(request)
        try:
            intent = _copilot(resolved_settings).interpret_scenario(body.request)
            result = build_twin_future_state_stress_test(
                service.model,
                service.engine.snapshot(),
                request.app.state.risk_model,
                request.app.state.cycle_model,
                request.app.state.bottleneck_model,
                request.app.state.anomaly_model,
                backend=body.backend,
                due_factor=intent.due_factor,
                time_limit=body.time_limit_seconds,
                replications=intent.replications,
                base_seed=body.base_seed,
                processing_cv=intent.processing_cv,
                mtbf=intent.mtbf,
                mttr=intent.mttr,
                risk_aversion=intent.risk_aversion,
                stressed_machine_id=intent.stressed_machine_id,
                stressed_machine_mtbf=intent.stressed_machine_mtbf,
                stressed_machine_mttr=intent.stressed_machine_mttr,
            )
        except (GeminiUnavailable, GurobiUnavailable) as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {
            "interpretation": {
                "evidence_label": "LLM-INTERPRETED INPUT — NOT AN ENGINEERING RESULT",
                "provider": "Google Gemini",
                "model": resolved_settings.gemini_model,
                **intent.model_dump(),
            },
            "engineering_result": result,
        }

    @application.post("/v1/copilot/explain")
    def explain(body: CopilotExplainIn, request: Request):
        service = get_service(request)
        try:
            stress = build_twin_future_state_stress_test(
                service.model,
                service.engine.snapshot(),
                request.app.state.risk_model,
                request.app.state.cycle_model,
                request.app.state.bottleneck_model,
                request.app.state.anomaly_model,
                backend=body.backend,
                due_factor=body.due_factor,
                replications=body.replications,
                base_seed=body.base_seed,
                processing_cv=body.processing_cv,
                mtbf=body.mtbf,
                mttr=body.mttr,
                risk_aversion=body.risk_aversion,
                stressed_machine_id=body.stressed_machine_id,
                stressed_machine_mtbf=body.stressed_machine_mtbf,
                stressed_machine_mttr=body.stressed_machine_mttr,
            )
            factory_payload = {
                "factory_id": service.model.factory_id,
                "source_kind": service.model.source_kind,
                "jobs": len(service.model.jobs),
                "machines": len(service.model.machines),
                "operations": service.model.operation_count,
            }
            evidence = _copilot_evidence(stress, factory_payload)
            answer = _copilot(resolved_settings).explain(body.question, evidence)
        except (GeminiUnavailable, GurobiUnavailable) as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {
            "evidence_label": "GEMINI EXPLANATION OF VALIDATED ENGINEERING OUTPUTS",
            "provider": "Google Gemini",
            "model": resolved_settings.gemini_model,
            "answer": answer.model_dump(),
            "engineering_evidence": evidence,
        }

    return application


app = create_app()
