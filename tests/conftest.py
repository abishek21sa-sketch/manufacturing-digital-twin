from __future__ import annotations

from pathlib import Path
import pytest

from mdt.data import load_orlib_instance


@pytest.fixture
def root() -> Path:
    return Path(__file__).resolve().parents[1]


@pytest.fixture
def ft06(root):
    return load_orlib_instance(root / "data/external/orlib/jobshop1.txt", "ft06")
