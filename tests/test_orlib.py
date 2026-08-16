from mdt.data import parse_orlib_instances


def test_ft06_public_benchmark_shape(ft06):
    assert ft06.metadata["instance"] == "ft06"
    assert len(ft06.jobs) == 6
    assert len(ft06.machines) == 6
    assert ft06.operation_count == 36
    assert ft06.total_work == 197.0


def test_ft06_first_route_matches_upstream(ft06):
    route = [(op.machine_id, op.processing_time) for op in ft06.jobs[0].operations]
    assert route == [("M2", 1.0), ("M0", 3.0), ("M1", 6.0), ("M3", 7.0), ("M5", 3.0), ("M4", 6.0)]
