"""Quality bar for the diagnosis engine, driven by the scenario library."""

from __future__ import annotations

import pytest

from diagnosis_evals import EVAL_SCENARIOS, DiagnosisScenario, format_scorecard, run_scenario
from test_aiops_diagnostics import migrated_database_url as migrated_database_url


@pytest.mark.asyncio
@pytest.mark.parametrize("scenario", EVAL_SCENARIOS, ids=[item.id for item in EVAL_SCENARIOS])
async def test_scenario_meets_quality_bar(
    migrated_database_url: str, scenario: DiagnosisScenario
) -> None:
    score = await run_scenario(scenario, migrated_database_url)

    failed = sorted(name for name, ok in score.checks.items() if not ok)
    assert score.passed, (
        f"场景 {scenario.id} 未达标,失败检查项: {failed}\n"
        f"task_status={score.task_status} assessment={score.assessment} "
        f"reportGeneration={score.report_generation} "
        f"citationValidation={score.citation_validation} "
        f"evidenceKinds={sorted(score.evidence_kinds)} "
        f"callCount={score.call_count} failedTools={score.failed_tools}"
    )
    assert score.score == 100.0
    assert score.llm_calls >= 1
    assert score.llm_latency_ms >= 0


@pytest.mark.asyncio
async def test_eval_scorecard_summary(migrated_database_url: str) -> None:
    scores = [await run_scenario(scenario, migrated_database_url) for scenario in EVAL_SCENARIOS]

    print(format_scorecard(scores))
    assert all(score.passed for score in scores)
    average = sum(score.score for score in scores) / len(scores)
    assert average >= 90.0
