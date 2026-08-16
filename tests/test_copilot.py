import json

import pytest

from mdt.copilot import EngineeringAnswer, GeminiCopilot, GeminiUnavailable, ScenarioIntent


class FakeTransport:
    def __init__(self):
        self.prompts = []

    def generate_json(self, *, prompt, schema):
        self.prompts.append(prompt)
        if schema is ScenarioIntent:
            return ScenarioIntent(
                scenario_label="M5 reliability stress",
                due_factor=1.4,
                processing_cv=0.12,
                mtbf=120,
                mttr=8,
                replications=24,
                risk_aversion=0.5,
                stressed_machine_id="M5",
                stressed_machine_mtbf=30,
                stressed_machine_mttr=14,
            ).model_dump_json()
        if schema is EngineeringAnswer:
            return EngineeringAnswer(
                answer="EDD has the lower supplied robust score.",
                evidence_used=["policy_summaries", "recommended_policy"],
                assumptions=["benchmark/synthetic scenario"],
                caveats=["not observed plant performance"],
                recommended_next_action="review the simulated tail-risk trade-off",
            ).model_dump_json()
        raise AssertionError(schema)


def test_copilot_interpretation_is_typed_and_bounded():
    transport = FakeTransport()
    copilot = GeminiCopilot(None, "gemini-test", transport=transport)
    intent = copilot.interpret_scenario("Stress M5 and favor tail risk")
    assert intent.stressed_machine_id == "M5"
    assert intent.replications == 24
    assert "Do not calculate schedules" in transport.prompts[0]


def test_copilot_explanation_is_grounded_by_prompt_contract():
    transport = FakeTransport()
    copilot = GeminiCopilot(None, "gemini-test", transport=transport)
    answer = copilot.explain("Why EDD?", {"recommended_policy": "EDD", "evidence_label": "SIMULATED"})
    assert "lower supplied robust score" in answer.answer
    assert "Use ONLY the supplied" in transport.prompts[0]
    assert "SIMULATED" in transport.prompts[0]


def test_copilot_requires_key_when_using_real_transport():
    with pytest.raises(GeminiUnavailable, match="GEMINI_API_KEY"):
        GeminiCopilot(None, "gemini-3.5-flash")


def test_google_transport_uses_chat_send_message(monkeypatch):
    import sys
    from types import ModuleType, SimpleNamespace

    from mdt.copilot.gemini import GoogleGenAITransport

    calls = {"create": 0, "send": 0, "models_generate": 0}

    class FakeGenerateContentConfig:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    class FakeChat:
        def send_message(self, *, message):
            calls["send"] += 1
            assert "scenario" in message.lower()
            return SimpleNamespace(text='{"scenario_label":"test"}')

    class FakeChats:
        def create(self, *, model, config):
            calls["create"] += 1
            assert model == "gemini-test"
            assert config.kwargs["response_mime_type"] == "application/json"
            return FakeChat()

    class FakeModels:
        def generate_content(self, **kwargs):
            calls["models_generate"] += 1
            raise AssertionError("direct models.generate_content must not be used")

    class FakeClient:
        def __init__(self, *, api_key):
            assert api_key == "test-key"
            self.chats = FakeChats()
            self.models = FakeModels()

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    google_module = ModuleType("google")
    genai_module = ModuleType("google.genai")
    types_module = ModuleType("google.genai.types")
    genai_module.Client = FakeClient
    genai_module.types = types_module
    types_module.GenerateContentConfig = FakeGenerateContentConfig
    google_module.genai = genai_module

    monkeypatch.setitem(sys.modules, "google", google_module)
    monkeypatch.setitem(sys.modules, "google.genai", genai_module)
    monkeypatch.setitem(sys.modules, "google.genai.types", types_module)

    transport = GoogleGenAITransport("test-key", "gemini-test")
    raw = transport.generate_json(prompt="Scenario request", schema=ScenarioIntent)
    assert raw == '{"scenario_label":"test"}'
    assert calls == {"create": 1, "send": 1, "models_generate": 0}
