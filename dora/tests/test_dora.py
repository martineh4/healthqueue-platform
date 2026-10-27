from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

import analyze
import generate
import metrics
from generate import Scenario

HERE = Path(__file__).parent.parent


@pytest.fixture(scope="module")
def baseline() -> generate.Dataset:
    return generate.simulate(generate.DEFAULT_SEED)


def test_same_seed_same_data():
    a, b = generate.simulate(5), generate.simulate(5)
    assert a.deployments == b.deployments
    assert a.changes == b.changes


def test_other_seed_other_data():
    assert generate.simulate(5).deployments != generate.simulate(6).deployments


def test_committed_data_matches_the_seed(tmp_path):
    generate.write(generate.simulate(generate.DEFAULT_SEED), tmp_path)
    for name in ("changes.csv", "deployments.csv", "toil.csv", "checkins.csv"):
        committed = (HERE / "data" / name).read_bytes()
        assert (tmp_path / name).read_bytes() == committed, (
            f"regenerate: python generate.py ({name})"
        )


def test_committed_report_and_charts_are_current():
    report, svg = analyze.build(HERE / "data", generate.DEFAULT_SEED)
    assert (analyze.DOCS / "dora-report.md").read_text(encoding="utf-8") == report, (
        "regenerate: python analyze.py"
    )
    for name, content in svg.items():
        assert (analyze.CHART_DIR / name).read_text(encoding="utf-8") == content, name


def test_window_and_volume(baseline):
    assert all(generate.START <= d["merged_at"] < generate.END for d in baseline.deployments)
    assert 40 <= len(baseline.deployments) <= 120
    assert len(baseline.changes) >= len(baseline.deployments)


def test_each_change_moves_forward_through_the_stages(baseline):
    by_id = {d["deployment_id"]: d for d in baseline.deployments}
    for c in baseline.changes:
        d = by_id[c["deployment_id"]]
        assert c["committed_at"] < c["pr_merged_at"] < c["released_at"] <= d["head_at"]
        assert d["head_at"] <= d["approved_at"] < d["merged_at"] < d["running_at"]


def test_human_steps_happen_at_check_ins(baseline):
    checkins = set(baseline.checkins)
    assert all(c["pr_merged_at"] in checkins for c in baseline.changes)
    assert all(d["approved_at"] in checkins for d in baseline.deployments)
    approvals = [t for t in baseline.toil if t["kind"] == "approve held CI runs"]
    assert len(approvals) == sum(d["approvals"] for d in baseline.deployments)


def test_failures_restore_after_they_start(baseline):
    failed = [d for d in baseline.deployments if "failure_cause" in d]
    assert failed
    for d in failed:
        assert d["running_at"] < d["detected_at"] <= d["responded_at"] < d["restored_at"]


def test_github_app_removes_the_approval_click():
    ds = generate.simulate(generate.DEFAULT_SEED, Scenario(github_app=True))
    assert all(d["approved_at"] is None for d in ds.deployments)
    assert not [t for t in ds.toil if t["kind"] == "approve held CI runs"]


def test_auto_rebase_removes_manual_branch_updates():
    ds = generate.simulate(generate.DEFAULT_SEED, Scenario(github_app=True, auto_rebase=True))
    assert not [t for t in ds.toil if t["kind"] == "update stale deploy branch"]


def test_smoke_test_stops_startup_crashes():
    for seed in range(1, 6):
        ds = generate.simulate(seed, Scenario(smoke_test=True))
        assert all(d.get("failure_cause") != "startup crash" for d in ds.deployments)


def test_load_round_trips_the_csv(tmp_path, baseline):
    generate.write(baseline, tmp_path)
    d = metrics.load(tmp_path)
    a = metrics.summarize(d["changes"], d["deployments"], d["toil"], generate.DAYS)
    b = metrics.summarize(baseline.changes, baseline.deployments, baseline.toil, generate.DAYS)
    assert (a.lead_median, a.failure_rate, a.recovery_median) == (
        b.lead_median,
        b.failure_rate,
        b.recovery_median,
    )


@pytest.mark.parametrize(
    ("per_day", "level"),
    [(1.01, "elite"), (1.0, "high"), (1 / 7, "high"), (0.14, "medium"), (1 / 31, "low")],
)
def test_frequency_level(per_day, level):
    assert metrics.frequency_level(per_day) == level


@pytest.mark.parametrize(
    ("t", "level"),
    [
        (timedelta(hours=23, minutes=59), "elite"),
        (timedelta(days=1), "high"),
        (timedelta(days=7), "high"),
        (timedelta(days=8), "medium"),
        (timedelta(days=31), "low"),
    ],
)
def test_lead_time_level(t, level):
    assert metrics.lead_time_level(t) == level


@pytest.mark.parametrize(
    ("rate", "level"),
    [(0.05, "elite"), (0.051, "high or medium"), (0.2, "high or medium"), (0.21, "low")],
)
def test_failure_rate_level(rate, level):
    assert metrics.failure_rate_level(rate) == level


@pytest.mark.parametrize(
    ("t", "level"),
    [
        (timedelta(minutes=59), "elite"),
        (timedelta(hours=1), "high or medium"),
        (timedelta(days=2), "between medium and low"),
        (timedelta(days=7), "low"),
    ],
)
def test_recovery_level(t, level):
    assert metrics.recovery_level(t) == level


def test_summarize_hand_built():
    t0 = datetime(2026, 8, 3, 14, tzinfo=UTC)
    h = timedelta(hours=1)
    changes = [
        {"committed_at": t0, "deployment_id": "D1"},
        {"committed_at": t0 + h, "deployment_id": "D1"},
        {"committed_at": t0, "deployment_id": "D2"},
    ]
    deployments = [
        {"deployment_id": "D1", "running_at": t0 + 3 * h, "change_ids": ["C1", "C2"]},
        {
            "deployment_id": "D2",
            "running_at": t0 + 10 * h,
            "change_ids": ["C3"],
            "failure_cause": "startup crash",
            "restored_at": t0 + 10.5 * h,
        },
    ]
    s = metrics.summarize(changes, deployments, [{"kind": "x", "minutes": 3}], days=2)
    assert s.per_day == 1
    assert s.lead_median == 3 * h  # lead times 3 h, 2 h, 10 h
    assert s.failure_rate == 0.5
    assert s.recovery_median == timedelta(minutes=30)
    assert s.toil_minutes == {"x": 3}


def test_durations_read_naturally():
    assert analyze.dur(timedelta(minutes=41)) == "41 min"
    assert analyze.dur(timedelta(hours=4, minutes=40)) == "4 h 40 min"
    assert analyze.dur(timedelta(hours=2)) == "2 h"
    assert analyze.dur(timedelta(days=2.8)) == "2.8 days"


def test_analysis_runs_without_the_simulation_only_files(tmp_path, baseline):
    generate.write(baseline, tmp_path)
    (tmp_path / "toil.csv").unlink()
    (tmp_path / "checkins.csv").unlink()
    report, _ = analyze.build(tmp_path, generate.DEFAULT_SEED)
    assert "| Manual toil | 0.0 h over 90 days |" in report
