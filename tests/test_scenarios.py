"""Every scenario in evals/scenarios.py, end to end through the real agent loop with a scripted model."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from evals.harness import run_mock  # noqa: E402
from evals.scenarios import SCENARIOS  # noqa: E402


def test_catalogue_is_big_and_unique():
    ids = [s.id for s in SCENARIOS]
    assert len(ids) == len(set(ids)) and 60 <= len(ids) <= 100
    assert len({s.category for s in SCENARIOS}) >= 12


@pytest.mark.parametrize("sc", SCENARIOS, ids=lambda s: s.id)
def test_scenario(sc):
    out = run_mock(sc)
    if out.skipped:
        pytest.skip(out.skipped)
    assert out.passed, "\n".join(out.problems)
