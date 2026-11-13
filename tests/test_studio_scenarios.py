"""Studio jobs through the real agent loop and a scripted model."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from evals.harness import run_mock  # noqa: E402
from evals.studio_scenarios import SCENARIOS  # noqa: E402


def test_each_studio_has_three_jobs():
    by = {}
    for sc in SCENARIOS:
        by.setdefault(sc.category, []).append(sc.id)
    for studio in ("document", "spreadsheet", "research", "visual", "developer"):
        assert len(by.get(studio, [])) >= 3, studio
    assert len({s.id for s in SCENARIOS}) == len(SCENARIOS)


@pytest.mark.parametrize("sc", SCENARIOS, ids=lambda s: s.id)
def test_studio_scenario(sc):
    out = run_mock(sc)
    if out.skipped:
        pytest.skip(out.skipped)
    assert out.passed, "\n".join(out.problems)
