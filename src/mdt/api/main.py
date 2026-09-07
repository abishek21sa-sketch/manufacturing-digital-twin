from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import asdict
from importlib.util import find_spec
import json
import logging
from pathlib import Path
from time import perf_counter
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.openapi.utils import get_openapi
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

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
from mdt.contracts import EVENT_CONTRACT_VERSION, event_contract
from mdt.copilot import GeminiCopilot, GeminiUnavailable
from mdt.audit import event_ledger
from mdt.data import CANONICAL_EVENT_COLUMNS, inspect_event_csv, replay_events, synthetic_dataset_summary
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
from mdt.planning import snapshot_state_id
from mdt.observability import MetricsRegistry
from mdt.security import AuthenticationError, authenticate_request
from mdt.service import TwinService
from mdt.simulation import PolicySpec, ReliabilitySpec, SimulationConfig, simulate, validate_simulation
from mdt.twin import TwinEngine, TwinStateError
from mdt.trust import TrustDecision, assess_trust
from mdt.optimization.signature_algorithm import reference_slot_problem, run_trust_rh_signature


logger = logging.getLogger("mdt.api")


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
    schema_version: str = Field(default=EVENT_CONTRACT_VERSION, min_length=1, max_length=32)
    source_system: str = Field(default="manual-api", min_length=1, max_length=128)
    source_event_id: str | None = Field(default=None, max_length=256)


class EventBatchIn(BaseModel):
    events: list[EventIn] = Field(min_length=1, max_length=500)
    source_system: str = Field(min_length=1, max_length=128)
    schema_version: str = Field(default=EVENT_CONTRACT_VERSION, min_length=1, max_length=32)
    idempotency_key: str = Field(min_length=8, max_length=256)


class ScheduleIn(BaseModel):
    backend: str = "auto"
    due_factor: float = Field(default=1.5, gt=0)
    makespan_weight: float = Field(default=0.05, ge=0)
    tardiness_weight: float = Field(default=1.0, ge=0)
    risk_tardiness_weight: float = Field(default=2.0, ge=0)
    use_ai_risk: bool = True
    time_limit_seconds: float = Field(default=30.0, gt=0, le=300)
    down_machine_recovery: dict[str, float] = Field(default_factory=dict)
    stability_penalty: float = Field(default=0.0, ge=0, le=100.0)


class RecoveryIn(BaseModel):
    backend: str = "auto"
    due_factor: float = Field(default=1.5, gt=0)
    time_limit_seconds: float = Field(default=30.0, gt=0, le=300)
    processing_cv: float = Field(default=0.10, ge=0, le=1.0)
    mtbf: float | None = Field(default=120.0, gt=0)
    mttr: float = Field(default=8.0, gt=0)
    down_machine_recovery: dict[str, float] = Field(default_factory=dict)
    stability_penalty: float = Field(default=0.0, ge=0, le=100.0)


class TrustedRecoveryIn(RecoveryIn):
    reference_time: float | None = Field(default=None, ge=0)
    freshness_horizon: float = Field(default=24.0, gt=0)
    authorize_threshold: float = Field(default=0.82, ge=0, le=1)
    review_threshold: float = Field(default=0.62, ge=0, le=1)


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
    stability_penalty: float = Field(default=0.0, ge=0, le=100.0)


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
        "state_id": snapshot_state_id(s),
        "timestamp": s.timestamp,
        "latest_observation_timestamp": s.timestamp,
        "event_count": s.event_count,
        "wip_jobs": s.wip_jobs,
        "completed_jobs": s.completed_jobs,
        "ready_operations": s.ready_operations,
        "running_operations": [k for k, v in s.operations.items() if v.status.value == "running"],
        "queued_operations": [k for k, v in s.operations.items() if v.status.value in {"ready", "not_ready"}],
        "completed_operations": [k for k, v in s.operations.items() if v.status.value == "complete"],
        "machines": {k: asdict(v) for k, v in s.machines.items()},
        "jobs": {k: asdict(v) for k, v in s.jobs.items()},
        "operations": {k: asdict(v) for k, v in s.operations.items()},
    }


def _event_from_input(body: EventIn, *, source_system: str | None = None, schema_version: str | None = None) -> ManufacturingEvent:
    resolved_source = source_system or body.source_system
    resolved_version = schema_version or body.schema_version
    if resolved_version != EVENT_CONTRACT_VERSION:
        raise ValueError(f"unsupported event contract version {resolved_version!r}")
    payload = dict(body.payload)
    payload["_mdt_contract"] = {
        "name": "mdt.manufacturing-event",
        "version": resolved_version,
        "source_system": resolved_source,
        "source_event_id": body.source_event_id,
    }
    return ManufacturingEvent(
        event_id=body.event_id or str(uuid4()),
        event_type=body.event_type,
        timestamp=body.timestamp,
        job_id=body.job_id,
        operation_id=body.operation_id,
        machine_id=body.machine_id,
        payload=payload,
    )


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
    resolved_settings.validate_operational()
    metrics = MetricsRegistry()

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
    application.state.metrics = metrics

    def custom_openapi() -> dict:
        if application.openapi_schema:
            return application.openapi_schema
        schema = get_openapi(
            title=application.title,
            version=application.version,
            description="Evidence-labeled manufacturing twin decisions with human disposition required before execution.",
            routes=application.routes,
        )
        schema.setdefault("components", {}).setdefault("securitySchemes", {}).update(
            {
                "mdtApiKey": {"type": "apiKey", "in": "header", "name": "X-MDT-API-Key"},
                "bearerAuth": {"type": "http", "scheme": "bearer"},
            }
        )
        for path, path_item in schema.get("paths", {}).items():
            if path.startswith("/v1/"):
                for operation in path_item.values():
                    if isinstance(operation, dict):
                        operation.setdefault("security", [{"mdtApiKey": []}, {"bearerAuth": []}])
        application.openapi_schema = schema
        return schema

    application.openapi = custom_openapi
    application.add_middleware(TrustedHostMiddleware, allowed_hosts=list(resolved_settings.allowed_hosts))
    if resolved_settings.cors_origins:
        application.add_middleware(
            CORSMiddleware,
            allow_origins=list(resolved_settings.cors_origins),
            allow_credentials=False,
            allow_methods=["GET", "POST", "OPTIONS"],
            allow_headers=["Authorization", "Content-Type", "X-MDT-API-Key", "X-Request-ID"],
        )

    @application.middleware("http")
    async def platform_middleware(request: Request, call_next):
        request_id = request.headers.get("X-Request-ID", "").strip()[:128] or str(uuid4())
        request.state.request_id = request_id
        started = perf_counter()
        try:
            request.state.principal = authenticate_request(resolved_settings, request)
        except AuthenticationError as exc:
            response = JSONResponse({"detail": exc.detail, "request_id": request_id}, status_code=exc.status_code)
        else:
            try:
                response = await call_next(request)
            except Exception:
                route = getattr(request.scope.get("route"), "path", request.url.path)
                if resolved_settings.observability_enabled:
                    metrics.observe_request(request.method, route, 500, perf_counter() - started)
                logger.exception("request_failed request_id=%s route=%s", request_id, route)
                raise
        route = getattr(request.scope.get("route"), "path", request.url.path)
        if resolved_settings.observability_enabled:
            metrics.observe_request(request.method, route, response.status_code, perf_counter() - started)
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        if request.url.path.startswith("/v1/") or request.url.path in {"/health", "/ready", "/metrics"}:
            response.headers["Cache-Control"] = "no-store"
        return response
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
    def health(request: Request):
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
            "instance_id": resolved_settings.instance_id,
            "environment": resolved_settings.environment,
            "auth_mode": resolved_settings.auth_mode,
            "schema_revision": resolved_settings.schema_revision,
            "request_id": request.state.request_id,
        }

    @application.get("/ready")
    def ready(request: Request):
        try:
            service = get_service(request)
            database = service.repository.healthcheck()
        except Exception as exc:
            return JSONResponse(
                {"status": "not_ready", "detail": str(exc), "request_id": request.state.request_id},
                status_code=503,
            )
        return {
            "status": "ready",
            "instance_id": resolved_settings.instance_id,
            "environment": resolved_settings.environment,
            "database": database,
            "models_loaded": all(
                getattr(request.app.state, name, None) is not None
                for name in ("risk_model", "cycle_model", "bottleneck_model", "anomaly_model")
            ),
            "request_id": request.state.request_id,
        }

    @application.get("/metrics", response_class=PlainTextResponse)
    def metrics_endpoint():
        return PlainTextResponse(metrics.render(), media_type="text/plain; version=0.0.4")

    @application.get("/v1/platform/contracts/events")
    def event_contract_endpoint():
        return event_contract(resolved_settings.event_contract_version)

    @application.get("/v1/ops/schema")
    def schema_endpoint(request: Request):
        return {
            "service": "manufacturing-digital-twin",
            "instance_id": resolved_settings.instance_id,
            "environment": resolved_settings.environment,
            "schema": get_service(request).repository.schema_info(),
            "contract": event_contract(resolved_settings.event_contract_version),
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

    @application.get("/v1/twin/ledger")
    def twin_ledger(request: Request):
        """Expose the replay chain as EVENT -> STATE CHANGE -> CURRENT TWIN."""
        service = get_service(request)
        events = service.repository.list_events()
        snapshot = service.engine.snapshot()
        return {
            "evidence_label": "OBSERVED / INGESTED EVENT LEDGER WITH DETERMINISTIC REPLAY",
            "twin_state_id": snapshot_state_id(snapshot),
            "event_count": len(events),
            "events": event_ledger(service.model, events),
        }

    def trust_assessment(request: Request, *, reference_time: float | None = None, freshness_horizon: float = 24.0, authorize_threshold: float = 0.82, review_threshold: float = 0.62):
        service = get_service(request)
        snapshot = service.engine.snapshot()
        model_evidence = {
            "lateness": request.app.state.risk_model is not None,
            "cycle_time": request.app.state.cycle_model is not None,
            "bottleneck": request.app.state.bottleneck_model is not None,
            "anomaly": request.app.state.anomaly_model is not None,
        }
        return assess_trust(
            snapshot=snapshot,
            factory_model=service.model,
            ledger_events=service.repository.list_events(),
            model_evidence=model_evidence,
            reference_time=reference_time,
            freshness_horizon=freshness_horizon,
            authorize_threshold=authorize_threshold,
            review_threshold=review_threshold,
        )

    @application.get("/v1/twin/trust")
    def twin_trust(
        request: Request,
        reference_time: float | None = None,
        freshness_horizon: float = 24.0,
        authorize_threshold: float = 0.82,
        review_threshold: float = 0.62,
    ):
        try:
            return trust_assessment(
                request,
                reference_time=reference_time,
                freshness_horizon=freshness_horizon,
                authorize_threshold=authorize_threshold,
                review_threshold=review_threshold,
            ).to_dict()
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @application.post("/v1/twin/events")
    def append_event(body: EventIn, request: Request):
        service = get_service(request)
        try:
            event = _event_from_input(body)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        try:
            service.engine.apply(event)
            service.repository.append(event)
        except Exception as exc:
            service.refresh()
            if isinstance(exc, TwinStateError):
                raise HTTPException(status_code=409, detail=str(exc)) from exc
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"event": asdict(event), "state": snapshot_payload(service)}

    @application.post("/v1/ingest/events")
    def ingest_events(body: EventBatchIn, request: Request):
        """Accept a versioned, idempotent at-least-once event batch.

        The candidate batch is replayed against a fresh engine before durable
        commit, so a malformed or contradictory batch cannot partially mutate
        the live twin.
        """
        service = get_service(request)
        try:
            events = [_event_from_input(item, source_system=body.source_system, schema_version=body.schema_version) for item in body.events]
            existing = service.repository.ingestion_batch(
                body.idempotency_key,
                events=events,
                source_system=body.source_system,
                schema_version=body.schema_version,
            )
            if existing is not None:
                return {
                    **existing,
                    "replayed": True,
                    "contract": event_contract(body.schema_version),
                    "state": snapshot_payload(service),
                }
            candidate = TwinEngine(service.model)
            candidate.replay(service.repository.list_events())
            for event in events:
                candidate.apply(event)
            result = service.repository.append_many(
                events,
                source_system=body.source_system,
                schema_version=body.schema_version,
                idempotency_key=body.idempotency_key,
            )
            service.refresh()
        except ValueError as exc:
            service.refresh()
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except TwinStateError as exc:
            service.refresh()
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {
            **result,
            "contract": event_contract(body.schema_version),
            "state": snapshot_payload(service),
        }

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
                stability_penalty=body.stability_penalty,
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

    @application.get("/v1/trust-rh/reference")
    def trust_rh_reference(request: Request, stability_penalty: float = 1.0):
        trust = trust_assessment(request)
        service = get_service(request)
        job_ids = [j.job_id for j in service.model.jobs][:6]
        costs, prior, capacity = reference_slot_problem(job_ids)
        result = run_trust_rh_signature(trust, job_ids, costs, prior, capacity, stability_penalty=stability_penalty)
        return {"trust": trust.to_dict(), "stability_schedule": result.to_dict(), "human_review_required": True}

    @application.post("/v1/decision/trusted-recovery")
    def trusted_recovery(body: TrustedRecoveryIn, request: Request):
        try:
            trust = trust_assessment(
                request,
                reference_time=body.reference_time,
                freshness_horizon=body.freshness_horizon,
                authorize_threshold=body.authorize_threshold,
                review_threshold=body.review_threshold,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        if trust.decision != TrustDecision.AUTHORIZED:
            service = get_service(request)
            snapshot = service.engine.snapshot()
            run_id = f"TRUST-RH-{uuid4()}"
            payload = {
                "run_id": run_id,
                "algorithm": "TRUST-RH",
                "trust": trust.to_dict(),
                "optimizer_executed": False,
                "status": trust.decision.value,
                "solver": {"backend": "NOT_EXECUTED", "status": "GATED"},
                "evidence_label": "GOVERNANCE GATE — OPTIMIZER NOT EXECUTED",
            }
            job_ids = [j.job_id for j in service.model.jobs][:6]
            costs, prior, capacity = reference_slot_problem(job_ids)
            payload["stability_schedule"] = run_trust_rh_signature(trust, job_ids, costs, prior, capacity).to_dict()
            service.repository.save_decision_run(
                run_id=run_id,
                decision_kind="trusted_recovery",
                twin_state_id=f"twin:{snapshot.event_count}:{snapshot.timestamp}",
                twin_timestamp=float(snapshot.timestamp),
                twin_event_count=int(snapshot.event_count),
                model_version=__version__,
                solver_backend="NOT_EXECUTED",
                data_version=f"{service.model.metadata.get('instance', 'unknown')}:{service.model.source_kind}",
                request_payload=body.model_dump(),
                result_payload=payload,
                status=trust.decision.value,
            )
            return payload

        recovery_body = RecoveryIn(**body.model_dump(include=set(RecoveryIn.model_fields)))
        result = recovery(recovery_body, request)
        result = dict(result)
        result["algorithm"] = "TRUST-RH"
        result["trust"] = trust.to_dict()
        result["optimizer_executed"] = True
        service = get_service(request)
        job_ids = [j.job_id for j in service.model.jobs][:6]
        costs, prior, capacity = reference_slot_problem(job_ids)
        result["stability_schedule"] = run_trust_rh_signature(trust, job_ids, costs, prior, capacity).to_dict()
        return result

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
                stability_penalty=body.stability_penalty,
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
            "supported_modes": ["PUBLIC_BENCHMARK", "SYNTHETIC_SCENARIO_ANALYTICS", "CANONICAL_CSV_HISTORICAL_REPLAY"],
            "live_stream_status": "EXTERNAL VALIDATION PENDING",
            "canonical_event_columns": list(CANONICAL_EVENT_COLUMNS),
            "sample_file": "data/samples/historical_events.csv",
            "synthetic_dataset": {
                "file": "data/synthetic/mdt_operational_scenarios_150000.csv",
                "summary_url": "/v1/data/synthetic",
                "download_url": "/v1/data/synthetic/download",
                "source_kind": "synthetic_demo",
            },
            "commit_policy": "uploaded CSV is validated and replayed in an isolated twin; it is never silently committed to the live event ledger",
        }

    @application.get("/v1/data/synthetic")
    def synthetic_data_summary():
        try:
            return synthetic_dataset_summary(str(resolved_settings.project_root))
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise HTTPException(status_code=500, detail="synthetic dataset package is unavailable") from exc

    @application.get("/v1/data/synthetic/download", include_in_schema=False)
    def synthetic_data_download():
        manifest_path = resolved_settings.project_root / "data" / "synthetic" / "DATASET_MANIFEST.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        csv_path = resolved_settings.project_root / "data" / "synthetic" / str(manifest.get("file", "mdt_operational_scenarios_150000.csv"))
        if not csv_path.exists():
            raise HTTPException(status_code=404, detail="synthetic dataset is unavailable")
        return FileResponse(csv_path, media_type="text/csv", filename=csv_path.name)

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
