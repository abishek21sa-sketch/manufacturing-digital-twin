import math
import pytest

from mdt.ie import availability, capacity_rate, identify_constraint, kingman_wait, little_law, reliability_exponential, utilization


def test_littles_law_reference_case():
    assert little_law(4.0, 2.5) == 10.0


def test_utilization_and_capacity_reference_cases():
    assert utilization(8.0, 10.0) == 0.8
    assert capacity_rate(480.0, 12.0) == 40.0


def test_reliability_math_reference_cases():
    assert availability(90.0, 10.0) == 0.9
    assert reliability_exponential(0.0, 100.0) == 1.0
    assert math.isclose(reliability_exponential(100.0, 100.0), math.e ** -1)


def test_kingman_m_m_1_equivalence():
    # For ca^2 = cs^2 = 1, Kingman reduces to rho/(1-rho) * E[S].
    assert math.isclose(kingman_wait(4.0, 5.0, 1.0, 1.0), 0.8)


def test_kingman_rejects_unstable_queue():
    with pytest.raises(ValueError):
        kingman_wait(5.0, 5.0, 1.0, 1.0)


def test_ft06_constraint_is_machine_2(ft06):
    result = identify_constraint(ft06)
    expected = {}
    for m in ft06.machines:
        expected[m.machine_id] = sum(op.processing_time for j in ft06.jobs for op in j.operations if op.machine_id == m.machine_id)
    assert result.machine_id == max(expected, key=expected.get)
    assert result.workload == expected[result.machine_id]
