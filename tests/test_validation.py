from dataclasses import replace
import pytest

from mdt.data import FactoryValidationError, validate_factory_model


def test_validation_rejects_nonpositive_processing_time(ft06):
    job = ft06.jobs[0]
    bad_op = replace(job.operations[0], processing_time=0)
    bad_job = replace(job, operations=(bad_op, *job.operations[1:]))
    bad_model = replace(ft06, jobs=(bad_job, *ft06.jobs[1:]))
    with pytest.raises(FactoryValidationError):
        validate_factory_model(bad_model)
