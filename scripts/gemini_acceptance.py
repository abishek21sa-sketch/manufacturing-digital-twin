from __future__ import annotations

import json
from pathlib import Path

from mdt.config import Settings
from mdt.copilot import GeminiCopilot, GeminiUnavailable


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    settings = Settings.from_env(root)
    if not settings.gemini_api_key:
        raise SystemExit(
            "GEMINI_ACCEPTANCE=FAIL: configure GEMINI_API_KEY in the repository .env file; do not paste the key into chat"
        )
    try:
        copilot = GeminiCopilot(settings.gemini_api_key, settings.gemini_model)
        intent = copilot.interpret_scenario(
            "Evaluate a manufacturing reliability stress scenario. Stress M5, use a moderate Monte Carlo sample, and favor tail-risk robustness."
        )
        answer = copilot.explain(
            "Which supplied policy is preferred and what must I remember about the evidence?",
            {
                "evidence_labels": {"future_state": "SIMULATED FUTURE-STATE STRESS TEST — SYNTHETIC/BENCHMARK INPUTS"},
                "policy_summaries": [
                    {"policy": "EDD_DISPATCH", "robust_score": 10.0, "cvar95_total_tardiness": 20.0},
                    {"policy": "BOX_ROBUST_AI", "robust_score": 15.0, "cvar95_total_tardiness": 30.0},
                ],
                "recommended_policy": "EDD_DISPATCH",
                "limitations": ["simulated benchmark evidence; not observed plant performance"],
            },
        )
    except GeminiUnavailable as exc:
        raise SystemExit(f"GEMINI_ACCEPTANCE=FAIL: {exc}") from exc

    payload = {
        "provider": "Google Gemini",
        "model": settings.gemini_model,
        "structured_scenario_parse": "PASS",
        "scenario_label": intent.scenario_label,
        "stressed_machine_id": intent.stressed_machine_id,
        "structured_explanation": "PASS",
        "answer_chars": len(answer.answer),
        "caveats": answer.caveats,
    }
    print(json.dumps(payload, indent=2))
    if not intent.scenario_label or not answer.answer:
        raise SystemExit("GEMINI_ACCEPTANCE=FAIL: empty structured output")
    print("GEMINI_ACCEPTANCE=PASS")


if __name__ == "__main__":
    main()
