"""Generate 90 days of synthetic HealthQueue deployment data (phase 11).

The model follows the real path of a change to production (ADR-0007):

1. an app pull request merges;
2. release.yml builds, scans, signs and verifies the image;
3. open-deploy-pr opens the deploy pull request, or replaces the open one;
4. the maintainer approves its held CI runs, the checks pass, and the maintainer merges it;
5. Argo CD picks up main within its 3-minute poll and rolls out (ADR-0006).

One maintainer does every human step, so those steps happen only when that person is at the
keyboard: a "check-in". Measured durations come from docs/evidence/phase-8-deploy-pr.md
(release 2m37s, open-deploy-pr 12s, rollout 27s). Everything else is an assumption, listed in
the constants below, so the results follow from them. The data is synthetic: it contains no
PHI and describes no real outage.

`simulate()` also takes a Scenario, so analyze.py can rerun the same seed with one process
change applied. Each kind of randomness has its own seeded stream, so a scenario changes only
what it touches.

Usage: python generate.py [--seed N] [--out DIR]
"""

from __future__ import annotations

import argparse
import csv
import math
import random
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

# 90 days ending 2026-10-26 00:00 in the maintainer's time zone, US Central. The whole window
# is daylight saving time (CDT, UTC-5; it ends 2026-11-01), so a fixed offset is exact.
START_LOCAL = date(2026, 7, 28)
DAYS = 90
LOCAL_OFFSET = timedelta(hours=-5)
START = datetime(2026, 7, 28, tzinfo=UTC) - LOCAL_OFFSET
END = START + timedelta(days=DAYS)
RUN_OUT_DAYS = 7  # keep simulating so changes merged near the end can still ship

DEFAULT_SEED = 11

# Maintainer availability
WORKDAY_START_H = (8.5, 9.5)  # local hours: first check-in falls in this range
WORKDAY_END_H = (17.5, 18.5)
CHECKIN_GAP_MIN = (10, 65)  # minimum gap, then the mean of an exponential on top
DAY_OFF_P = 0.06  # weekdays with no work at all (leave, illness)
WEEKEND_CHECKIN_P = 0.3  # chance of one weekend check-in, between 10:00 and 20:00
STAY_FOR_CHECKS_P = 0.6  # waits at the keyboard for a ~2-minute CI run instead of leaving

# Changes
APP_CHANGES_PER_WORKDAY = 1.4  # Poisson mean
READY_MEDIAN_MIN, READY_SIGMA = 40, 0.8  # commit -> PR checks green and self-reviewed
OTHER_MERGE_P = 0.12  # chance a check-in also merges a non-app PR (docs, infra, deps)

# Pipeline (measured in phase 8 unless noted)
RELEASE_S, RELEASE_SD_S = 157, 15
RELEASE_FLAKE_P = 0.05  # assumption: a transient failure (registry, scanner database)
OPEN_DEPLOY_PR_S = 12
PR_CI_S, PR_CI_SD_S = 140, 20  # required checks on the deploy PR
ARGOCD_POLL_S = 180
ROLLOUT_S, ROLLOUT_SD_S = 27, 4
BOT_REBASE_S = 30

# Failures
DEFECT_P = 0.05  # chance one app change breaks production
DEFECT_CAUSES = {  # cause: (weight, detection, detect delay range in minutes)
    "latency regression": (0.40, "page", (6, 20)),  # fast-burn latency alert
    "startup crash": (0.25, "page", (5, 8)),  # HealthQueueAPIUnavailable
    "errors on one route": (0.35, "ticket", (60, 360)),  # slow-burn availability alert
}
PAGE_RESPONSE_MIN = {"work": (3, 10), "off": (15, 45)}
REVERT_PR_MIN = (8, 15)  # open the revert PR (CI runs without approval: maintainer-authored)
REVERT_SCRIPTED_MIN = (1, 3)
POST_INCIDENT_MIN = 30

# Toil, minutes of hands-on work per event
TOIL_MIN = {
    "approve held CI runs": 2,
    "update stale deploy branch": 3,
    "rerun failed release": 5,
    "rotate kind pull secret": 5,
}
PULL_SECRET_DAYS = 29  # 30-day password, rotated a day early (ADR-0004; kind only)


@dataclass(frozen=True)
class Scenario:
    """Process changes analyze.py can test against the same seed."""

    github_app: bool = False  # deploy PR CI runs without the approval click (ADR-0007)
    auto_rebase: bool = False  # the bot rebuilds the deploy branch when main moves
    smoke_test: bool = False  # a pre-production smoke test stops startup crashes
    scripted_revert: bool = False  # one command opens the revert PR for a deploy


@dataclass
class Dataset:
    changes: list[dict] = field(default_factory=list)
    deployments: list[dict] = field(default_factory=list)
    checkins: list[datetime] = field(default_factory=list)
    toil: list[dict] = field(default_factory=list)


def _rng(seed: int, stream: str) -> random.Random:
    return random.Random(f"{seed}:{stream}")


def _minutes(m: float) -> timedelta:
    return timedelta(minutes=m)


def _seconds(s: float) -> timedelta:
    return timedelta(seconds=round(s))


def _toil(at: datetime, kind: str) -> dict:
    return {"at": at, "kind": kind, "minutes": TOIL_MIN[kind]}


def _poisson(r: random.Random, mean: float) -> int:
    limit, k, p = math.exp(-mean), 0, r.random()
    while p > limit:
        k += 1
        p *= r.random()
    return k


def is_work_hours(t: datetime) -> bool:
    local = t + LOCAL_OFFSET
    return local.weekday() < 5 and 8 <= local.hour < 18


def _checkins(seed: int) -> list[datetime]:
    r = _rng(seed, "checkins")
    out = []
    for d in range(DAYS + RUN_OUT_DAYS):
        midnight = START + timedelta(days=d)
        if (START_LOCAL + timedelta(days=d)).weekday() >= 5:
            if r.random() < WEEKEND_CHECKIN_P:
                out.append(midnight + timedelta(hours=r.uniform(10, 20)))
            continue
        if r.random() < DAY_OFF_P:
            continue
        t = midnight + timedelta(hours=r.uniform(*WORKDAY_START_H))
        end = midnight + timedelta(hours=r.uniform(*WORKDAY_END_H))
        while t < end:
            out.append(t)
            t += _minutes(CHECKIN_GAP_MIN[0] + r.expovariate(1 / CHECKIN_GAP_MIN[1]))
    return [t.replace(microsecond=0) for t in out]


class _Clock:
    """The maintainer's check-ins: find the next one at or after a time."""

    def __init__(self, times: list[datetime]):
        self.times = times

    def next(self, t: datetime) -> datetime | None:
        lo, hi = 0, len(self.times)
        while lo < hi:
            mid = (lo + hi) // 2
            if self.times[mid] < t:
                lo = mid + 1
            else:
                hi = mid
        return self.times[lo] if lo < len(self.times) else None


def _changes(seed: int, clock: _Clock, toil: list[dict]) -> list[dict]:
    r, rel, defects = _rng(seed, "changes"), _rng(seed, "release"), _rng(seed, "defects")
    causes = list(DEFECT_CAUSES)
    weights = [DEFECT_CAUSES[c][0] for c in causes]
    by_day: dict[int, list[datetime]] = {}
    for t in clock.times:
        by_day.setdefault((t - START).days, []).append(t)
    out = []
    for d in range(DAYS):
        day = by_day.get(d, [])
        if (START_LOCAL + timedelta(days=d)).weekday() >= 5 or len(day) < 2:
            continue
        for _ in range(_poisson(r, APP_CHANGES_PER_WORKDAY)):
            committed = day[0] + (day[-1] - day[0]) * r.random()
            ready = committed + _minutes(READY_MEDIAN_MIN * r.lognormvariate(0, READY_SIGMA))
            merged = clock.next(ready)
            if merged is None:
                continue
            released = merged + _seconds(rel.gauss(RELEASE_S, RELEASE_SD_S))
            if rel.random() < RELEASE_FLAKE_P:
                rerun = clock.next(released)
                if rerun is None:
                    continue
                toil.append(_toil(rerun, "rerun failed release"))
                released = rerun + _seconds(rel.gauss(RELEASE_S, RELEASE_SD_S))
            defect = defects.choices(causes, weights)[0] if defects.random() < DEFECT_P else None
            out.append(
                {
                    "committed_at": committed.replace(microsecond=0),
                    "pr_merged_at": merged,
                    "released_at": released,
                    "defect": defect,
                }
            )
    out.sort(key=lambda c: c["released_at"])
    for i, c in enumerate(out, 1):
        c["change_id"] = f"C{i:03d}"
    return out


def _other_merges(seed: int, clock: _Clock) -> list[datetime]:
    r = _rng(seed, "other")
    return [
        t + _minutes(r.uniform(0, 5))
        for t in clock.times
        if is_work_hours(t) and r.random() < OTHER_MERGE_P
    ]


def _incident(r: random.Random, sc: Scenario, clock: _Clock, running: datetime, cause: str):
    _, detection, (lo, hi) = DEFECT_CAUSES[cause]
    detected = running + _minutes(r.uniform(lo, hi))
    if detection == "page":
        hours = "work" if is_work_hours(detected) else "off"
        responded = detected + _minutes(r.uniform(*PAGE_RESPONSE_MIN[hours]))
    else:
        responded = clock.next(detected) or detected
    restored = (
        responded
        + _minutes(r.uniform(*(REVERT_SCRIPTED_MIN if sc.scripted_revert else REVERT_PR_MIN)))
        + _seconds(r.gauss(PR_CI_S, PR_CI_SD_S))
        + _minutes(1)
        + _seconds(r.uniform(0, ARGOCD_POLL_S) + r.gauss(ROLLOUT_S, ROLLOUT_SD_S))
    )
    return {
        "failure_cause": cause,
        "detection": detection,
        "detected_at": detected.replace(microsecond=0),
        "responded_at": responded.replace(microsecond=0),
        "restored_at": restored.replace(microsecond=0),
    }


def _deploys(seed: int, sc: Scenario, clock: _Clock, changes, others, toil) -> list[dict]:
    ci, stay, sync, inc = (_rng(seed, s) for s in ("ci", "stay", "sync", "incidents"))
    releases = list(changes)  # sorted by released_at
    deployments: list[dict] = []
    pr: dict | None = None

    def ci_done(t: datetime) -> datetime:
        return t + _seconds(ci.gauss(PR_CI_S, PR_CI_SD_S))

    def new_head(t: datetime) -> None:
        pr["head_at"] = pr["base_at"] = t
        pr["approved_at"] = None
        pr["green_at"] = ci_done(t) if sc.github_app else None

    def take_releases(until: datetime) -> None:
        nonlocal pr
        while releases and releases[0]["released_at"] <= until:
            c = releases.pop(0)
            head = c["released_at"] + _seconds(OPEN_DEPLOY_PR_S)
            if pr is None:
                pr = {"opened_at": head, "changes": [], "approvals": 0, "updates": 0}
            pr["changes"].append(c)
            new_head(head)

    def main_moved(after: datetime, until: datetime) -> datetime | None:
        return next((m for m in others if after < m <= until), None)

    for c in clock.times:
        take_releases(c)
        if pr is None:
            continue
        if sc.auto_rebase and (moved := main_moved(pr["base_at"], c)):
            new_head(moved + _seconds(BOT_REBASE_S))
            pr["updates"] += 1
        if pr["green_at"] is None:  # CI held until the maintainer approves it
            if pr["head_at"] > c:
                continue
            pr["approved_at"] = c
            pr["approvals"] += 1
            toil.append(_toil(c, "approve held CI runs"))
            pr["green_at"] = ci_done(c)
        # Merge in this visit if the checks are green, or turn green while the maintainer waits.
        now = c
        while pr is not None and pr["green_at"] is not None:
            if pr["green_at"] > now and stay.random() >= STAY_FOR_CHECKS_P:
                break
            at = max(now, pr["green_at"]) + _minutes(1)
            take_releases(at)
            if pr["green_at"] is None:  # a newer release replaced the head while waiting
                break
            if moved := main_moved(pr["base_at"], at):  # strict protection: branch is behind
                if sc.auto_rebase:  # the bot rebuilds the branch; its CI is held again
                    new_head(moved + _seconds(BOT_REBASE_S))
                    pr["updates"] += 1
                    if pr["green_at"] is None:
                        break
                    continue
                toil.append(_toil(at, "update stale deploy branch"))
                pr["updates"] += 1
                pr["base_at"] = at
                pr["green_at"] = ci_done(at)  # pushed by the maintainer: no approval needed
                now = at
                continue
            merged = at.replace(microsecond=0)
            running = merged + _seconds(
                sync.uniform(0, ARGOCD_POLL_S) + sync.gauss(ROLLOUT_S, ROLLOUT_SD_S)
            )
            causes = [x["defect"] for x in pr["changes"] if x["defect"]]
            if sc.smoke_test:
                causes = [x for x in causes if x != "startup crash"]
            d = {
                "deployment_id": f"D{len(deployments) + 1:03d}",
                "opened_at": pr["opened_at"],
                "head_at": pr["head_at"],
                "approved_at": pr["approved_at"],
                "merged_at": merged,
                "running_at": running,
                "change_ids": [x["change_id"] for x in pr["changes"]],
                "approvals": pr["approvals"],
                "branch_updates": pr["updates"],
            }
            d.update(_incident(inc, sc, clock, running, causes[0]) if causes else {})
            for x in pr["changes"]:
                x["deployment_id"] = d["deployment_id"]
            deployments.append(d)
            pr = None
    return [d for d in deployments if d["merged_at"] < END]


def simulate(seed: int = DEFAULT_SEED, scenario: Scenario | None = None) -> Dataset:
    sc = scenario or Scenario()
    toil: list[dict] = []
    clock = _Clock(_checkins(seed))
    changes = _changes(seed, clock, toil)
    deployments = _deploys(seed, sc, clock, changes, _other_merges(seed, clock), toil)
    shipped = {d["deployment_id"] for d in deployments}
    for d in deployments:
        if "failure_cause" in d:
            toil.append(
                {
                    "at": d["responded_at"],
                    "kind": "revert a failed deployment",
                    "minutes": round((d["restored_at"] - d["responded_at"]).total_seconds() / 60)
                    + POST_INCIDENT_MIN,
                }
            )
    t = START + timedelta(days=1)
    while t < END:
        toil.append(_toil(t, "rotate kind pull secret"))
        t += timedelta(days=PULL_SECRET_DAYS)
    return Dataset(
        changes=[c for c in changes if c.get("deployment_id") in shipped],
        deployments=deployments,
        checkins=[t for t in clock.times if t < END],
        toil=sorted((x for x in toil if x["at"] < END), key=lambda x: x["at"]),
    )


# CSV: the files a real export from the GitHub API would also produce (ADR-0007's marker).

CHANGE_FIELDS = ["change_id", "committed_at", "pr_merged_at", "released_at", "deployment_id"]
DEPLOY_FIELDS = [
    "deployment_id",
    "opened_at",
    "head_at",
    "approved_at",
    "merged_at",
    "running_at",
    "change_ids",
    "approvals",
    "branch_updates",
    "failure_cause",
    "detection",
    "detected_at",
    "responded_at",
    "restored_at",
]
TOIL_FIELDS = ["at", "kind", "minutes"]


def fmt(v) -> str:
    if v is None:
        return ""
    if isinstance(v, datetime):
        return v.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(v, list):
        return " ".join(v)
    return str(v)


def write(ds: Dataset, out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    tables = [
        ("changes.csv", CHANGE_FIELDS, ds.changes),
        ("deployments.csv", DEPLOY_FIELDS, ds.deployments),
        ("toil.csv", TOIL_FIELDS, ds.toil),
        ("checkins.csv", ["at"], [{"at": t} for t in ds.checkins]),
    ]
    for name, fields, rows in tables:
        with (out / name).open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f, lineterminator="\n")
            w.writerow(fields)
            for row in rows:
                w.writerow([fmt(row.get(k)) for k in fields])


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--seed", type=int, default=DEFAULT_SEED)
    p.add_argument("--out", type=Path, default=Path(__file__).parent / "data")
    args = p.parse_args()
    ds = simulate(args.seed)
    write(ds, args.out)
    print(
        f"seed {args.seed}: {len(ds.changes)} changes, {len(ds.deployments)} deployments, "
        f"{sum('failure_cause' in d for d in ds.deployments)} failed -> {args.out}"
    )


if __name__ == "__main__":
    main()
