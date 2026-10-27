"""DORA metrics and the 2024 performance levels (phase 11).

Works on the CSV files generate.py writes. A real export from the GitHub API (the deploy pull
requests' `healthqueue-release` marker, ADR-0007) would have the same columns.
"""

from __future__ import annotations

import csv
import statistics
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

HOUR, DAY = timedelta(hours=1), timedelta(days=1)

# Accelerate State of DevOps Report 2024, "Performance levels" (page 13). The 2025 report
# publishes no levels, so this is the most recent table.
LEVELS = ["elite", "high", "medium", "low"]
BENCHMARKS = {
    "elite": {
        "frequency": "On demand (multiple deploys per day)",
        "lead_time": "Less than one day",
        "failure_rate": "5%",
        "recovery": "Less than one hour",
        "share": "19%",
    },
    "high": {
        "frequency": "Between once per day and once per week",
        "lead_time": "Between one day and one week",
        "failure_rate": "20%",
        "recovery": "Less than one day",
        "share": "22%",
    },
    "medium": {
        "frequency": "Between once per week and once per month",
        "lead_time": "Between one week and one month",
        "failure_rate": "10%",
        "recovery": "Less than one day",
        "share": "35%",
    },
    "low": {
        "frequency": "Between once per month and once every six months",
        "lead_time": "Between one month and six months",
        "failure_rate": "40%",
        "recovery": "Between one week and one month",
        "share": "25%",
    },
}


def frequency_level(per_day: float) -> str:
    if per_day > 1:
        return "elite"
    if per_day >= 1 / 7:
        return "high"
    return "medium" if per_day >= 1 / 30 else "low"


def lead_time_level(t: timedelta) -> str:
    if t < DAY:
        return "elite"
    if t <= 7 * DAY:
        return "high"
    return "medium" if t <= 30 * DAY else "low"


def failure_rate_level(rate: float) -> str:
    # In 2024 the rate does not order the levels (medium 10% < high 20%), so it can only say
    # elite, high-or-medium, or low.
    if rate <= 0.05:
        return "elite"
    return "high or medium" if rate <= 0.20 else "low"


def recovery_level(t: timedelta) -> str:
    if t < HOUR:
        return "elite"
    if t < DAY:
        return "high or medium"
    return "between medium and low" if t < 7 * DAY else "low"


def parse_time(s: str) -> datetime | None:
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC) if s else None


def _read(path: Path, optional: bool = False) -> list[dict]:
    if optional and not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def load(data: Path) -> dict[str, list]:
    """Read the CSVs back into the shapes generate.simulate() returns."""
    times = {
        "at",
        "committed_at",
        "pr_merged_at",
        "released_at",
        "opened_at",
        "head_at",
        "approved_at",
        "merged_at",
        "running_at",
        "detected_at",
        "responded_at",
        "restored_at",
    }

    def row(r: dict) -> dict:
        out = {}
        for k, v in r.items():
            if k in times:
                out[k] = parse_time(v)
            elif k in ("approvals", "branch_updates", "minutes"):
                out[k] = int(v)
            elif k == "change_ids":
                out[k] = v.split()
            elif v:
                out[k] = v
        return out

    return {
        "changes": [row(r) for r in _read(data / "changes.csv")],
        "deployments": [row(r) for r in _read(data / "deployments.csv")],
        # Only the simulation knows these; a GitHub export has no check-ins or toil log.
        "toil": [row(r) for r in _read(data / "toil.csv", optional=True)],
        "checkins": [parse_time(r["at"]) for r in _read(data / "checkins.csv", optional=True)],
    }


def median_td(values: list[timedelta]) -> timedelta:
    return timedelta(seconds=statistics.median(v.total_seconds() for v in values))


def quantile_td(values: list[timedelta], q: float) -> timedelta:
    s = sorted(v.total_seconds() for v in values)
    return timedelta(seconds=s[min(len(s) - 1, round(q * (len(s) - 1)))])


@dataclass
class Summary:
    days: int
    deployments: int
    changes: int
    per_day: float
    lead_times: list[timedelta]
    lead_median: timedelta
    lead_p90: timedelta
    failed: int
    failure_rate: float
    recoveries: list[timedelta]
    recovery_median: timedelta | None
    toil_minutes: dict[str, int]

    @property
    def levels(self) -> dict[str, str]:
        return {
            "frequency": frequency_level(self.per_day),
            "lead_time": lead_time_level(self.lead_median),
            "failure_rate": failure_rate_level(self.failure_rate),
            "recovery": recovery_level(self.recovery_median) if self.recovery_median else "n/a",
        }


def summarize(changes: list[dict], deployments: list[dict], toil: list[dict], days: int):
    running = {d["deployment_id"]: d["running_at"] for d in deployments}
    lead = [running[c["deployment_id"]] - c["committed_at"] for c in changes]
    failed = [d for d in deployments if d.get("failure_cause")]
    recoveries = [d["restored_at"] - d["running_at"] for d in failed]
    toil_minutes: dict[str, int] = {}
    for t in toil:
        toil_minutes[t["kind"]] = toil_minutes.get(t["kind"], 0) + t["minutes"]
    return Summary(
        days=days,
        deployments=len(deployments),
        changes=len(changes),
        per_day=len(deployments) / days,
        lead_times=lead,
        lead_median=median_td(lead),
        lead_p90=quantile_td(lead, 0.9),
        failed=len(failed),
        failure_rate=len(failed) / len(deployments),
        recoveries=recoveries,
        recovery_median=median_td(recoveries) if recoveries else None,
        toil_minutes=dict(sorted(toil_minutes.items(), key=lambda kv: -kv[1])),
    )


STAGES = [
    ("Code review and PR checks", "committed_at", "pr_merged_at"),
    ("Release: build, scan, sign", "pr_merged_at", "released_at"),
    ("Waiting for the approval click", "released_at", "approved_at"),
    ("Deploy PR checks and merge", "approved_at", "merged_at"),
    ("Argo CD sync and rollout", "merged_at", "running_at"),
]


def stage_totals(changes: list[dict], deployments: list[dict]) -> list[tuple[str, timedelta]]:
    """Total time all changes spent in each stage, from commit to running in production."""
    by_id = {d["deployment_id"]: d for d in deployments}
    totals = []
    for name, start, end in STAGES:
        total = timedelta()
        for c in changes:
            row = {**by_id[c["deployment_id"]], **c}
            total += row[end] - row[start]
        totals.append((name, total))
    return totals
