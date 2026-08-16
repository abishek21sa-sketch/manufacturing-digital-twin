from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Protocol

from pydantic import BaseModel, Field


class GeminiUnavailable(RuntimeError):
    pass


class ScenarioIntent(BaseModel):
    scenario_label: str = Field(min_length=1, max_length=120)
    due_factor: float = Field(default=1.5, ge=0.5, le=4.0)
    processing_cv: float = Field(default=0.10, ge=0.0, le=0.75)
    mtbf: float | None = Field(default=120.0, ge=5.0, le=10_000.0)
    mttr: float = Field(default=8.0, ge=0.1, le=500.0)
    replications: int = Field(default=24, ge=4, le=200)
    risk_aversion: float = Field(default=0.35, ge=0.0, le=3.0)
    stressed_machine_id: str | None = Field(default=None, pattern=r"^M\d+$")
    stressed_machine_mtbf: float | None = Field(default=None, ge=1.0, le=10_000.0)
    stressed_machine_mttr: float | None = Field(default=None, ge=0.1, le=500.0)
    unsupported_requests: list[str] = Field(default_factory=list)
    interpretation_notes: list[str] = Field(default_factory=list)


class EngineeringAnswer(BaseModel):
    answer: str = Field(min_length=1, max_length=4000)
    evidence_used: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    caveats: list[str] = Field(default_factory=list)
    recommended_next_action: str | None = Field(default=None, max_length=600)


class JsonTransport(Protocol):
    def generate_json(self, *, prompt: str, schema: type[BaseModel]) -> str: ...


@dataclass
class GoogleGenAITransport:
    api_key: str
    model: str = "gemini-2.5-flash"

    def generate_json(self, *, prompt: str, schema: type[BaseModel]) -> str:
        try:
            from google import genai
            from google.genai import types
        except ImportError as exc:  # pragma: no cover - exercised on Windows acceptance when installed
            raise GeminiUnavailable("google-genai is not installed; install the 'gemini' project extra") from exc

        # The SDK client owns HTTP connections; an explicit context manager is
        # used so Windows resource cleanup is deterministic.
        try:
            with genai.Client(api_key=self.api_key) as client:
                config = types.GenerateContentConfig(
                    temperature=0.0,
                    response_mime_type="application/json",
                    response_json_schema=schema.model_json_schema(),
                )
                # Use the SDK chat helper for the request. This avoids the
                # direct-generate automatic-function-calling warning while
                # preserving the same schema-constrained, single-turn contract.
                chat = client.chats.create(model=self.model, config=config)
                response = chat.send_message(message=prompt)
        except Exception as exc:  # provider errors are surfaced, not disguised as deterministic results
            raise GeminiUnavailable(f"Gemini request failed: {exc}") from exc
        if not response.text:
            raise GeminiUnavailable("Gemini returned no text response")
        return response.text


class GeminiCopilot:
    """LLM layer above deterministic manufacturing calculations.

    Gemini is restricted to two roles:
    * translate natural-language scenario intent into bounded, typed parameters;
    * explain already-computed evidence without performing engineering math.
    """

    def __init__(self, api_key: str | None, model: str, transport: JsonTransport | None = None):
        if transport is None:
            if not api_key:
                raise GeminiUnavailable("GEMINI_API_KEY is not configured")
            transport = GoogleGenAITransport(api_key=api_key, model=model)
        self.transport = transport
        self.model = model

    def interpret_scenario(self, request: str) -> ScenarioIntent:
        prompt = (
            "You are translating a manufacturing digital-twin scenario request into bounded tool parameters. "
            "Do not calculate schedules, predict outcomes, or invent factory facts. "
            "Map only supported concepts: due-date tightness (due_factor), processing-time uncertainty (processing_cv), "
            "mean time between failures (mtbf), mean time to repair (mttr), Monte Carlo replications, risk aversion, "
            "and an optional specifically stressed machine with its own MTBF/MTTR. "
            "Put any unsupported request in unsupported_requests. Use conservative defaults when a parameter is absent.\n\n"
            f"USER SCENARIO REQUEST:\n{request.strip()}"
        )
        raw = self.transport.generate_json(prompt=prompt, schema=ScenarioIntent)
        return ScenarioIntent.model_validate_json(raw)

    def explain(self, question: str, evidence: dict[str, Any]) -> EngineeringAnswer:
        evidence_json = json.dumps(evidence, sort_keys=True, separators=(",", ":"), default=str)
        prompt = (
            "You are an engineering decision explainer for a manufacturing digital twin. "
            "Use ONLY the supplied deterministic/model evidence. Never invent measurements, savings, causal claims, or probabilities. "
            "Preserve evidence labels such as PREDICTED, OPTIMIZED, SIMULATED, CALCULATED, and EXTERNAL VALIDATION PENDING. "
            "If the question cannot be answered from the evidence, say that explicitly. "
            "Engineering calculations have already been performed by deterministic tools; do not redo or override them.\n\n"
            f"QUESTION:\n{question.strip()}\n\nENGINEERING EVIDENCE JSON:\n{evidence_json}"
        )
        raw = self.transport.generate_json(prompt=prompt, schema=EngineeringAnswer)
        return EngineeringAnswer.model_validate_json(raw)
