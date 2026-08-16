from pathlib import Path

from mdt.data import inspect_event_csv, replay_events


def test_sample_historical_event_csv_is_ready_and_replays(ft06, root):
    text = (root / "data/samples/historical_events.csv").read_text(encoding="utf-8")
    report, events = inspect_event_csv(text, ft06)
    assert report.ready is True
    assert report.errors == 0
    assert report.events_parsed == 3
    state = replay_events(ft06, events)
    assert state["event_count"] == 3
    assert state["operations"]["J0-O0"]["status"] == "complete"
    assert "J0-O1" in state["ready_operations"]


def test_event_csv_missing_columns_is_not_ready(ft06):
    report, events = inspect_event_csv("event_id,event_type\na,job_released\n", ft06)
    assert report.ready is False
    assert report.errors == 1
    assert events == ()
    assert report.issues[0].code == "MISSING_COLUMNS"


def test_event_csv_rejects_semantically_impossible_replay(ft06):
    text = """event_id,event_type,timestamp,job_id,operation_id,machine_id,payload_json\ne1,job_released,0,J0,,,{}\ne2,operation_started,0,J0,J0-O1,M0,{}\n"""
    report, _ = inspect_event_csv(text, ft06)
    assert report.ready is False
    assert any(issue.code == "TWIN_STATE_REJECTED" for issue in report.issues)
