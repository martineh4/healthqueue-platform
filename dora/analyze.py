"""Analyze the deployment data against the DORA 2024 levels and write the report (phase 11).

Reads dora/data/*.csv, writes the charts to docs/dora/ and docs/dora-report.md from
report_template.md. Every number in the report is filled in here, so the text cannot drift
from the data. Projections rerun generate.simulate() with the same seed and one process
change (generate.Scenario).

Usage: python analyze.py [--data DIR] [--seed N]
"""

from __future__ import annotations

import argparse
from datetime import timedelta
from pathlib import Path
from string import Template

import charts
import generate
import metrics
from metrics import BENCHMARKS, DAY, HOUR, LEVELS

HERE = Path(__file__).parent
DOCS = HERE.parent / "docs"
CHART_DIR = DOCS / "dora"


def dur(t: timedelta) -> str:
    """Human duration: 41 min, 4 h 40 min, 2.8 days."""
    s = t.total_seconds()
    if s < 3600:
        return f"{round(s / 60)} min"
    if s < 2 * 86400:
        h, m = divmod(round(s / 60), 60)
        return f"{h} h {m} min" if m else f"{h} h"
    return f"{s / 86400:.1f} days"


def pct(x: float) -> str:
    return f"{x * 100:.1f}%"


def hours(minutes: float) -> str:
    return f"{minutes / 60:.1f} h"


def weekly(deployments: list[dict]) -> tuple[list[str], list[int]]:
    labels, counts = [], []
    for w in range(0, generate.DAYS, 7):
        start = generate.START + timedelta(days=w)
        end = min(start + timedelta(days=7), generate.END)
        local = generate.START_LOCAL + timedelta(days=w)
        labels.append(local.strftime("%b %d").replace(" 0", " "))
        counts.append(sum(start <= d["merged_at"] < end for d in deployments))
    return labels, counts


LEAD_BUCKETS = [
    ("< 1 h", HOUR),
    ("1–4 h", 4 * HOUR),
    ("4–12 h", 12 * HOUR),
    ("12–24 h", DAY),
    ("1–3 d", 3 * DAY),
    ("3–7 d", 7 * DAY),
    ("> 7 d", None),
]


def lead_histogram(lead: list[timedelta]) -> list[int]:
    counts = [0] * len(LEAD_BUCKETS)
    for t in lead:
        i = next(i for i, (_, hi) in enumerate(LEAD_BUCKETS) if hi is None or t < hi)
        counts[i] += 1
    return counts


def friday_slowest(changes: list[dict], deployments: list[dict]) -> int:
    """How many of the slowest changes in a row were committed on a Friday (local time)."""
    running = {d["deployment_id"]: d["running_at"] for d in deployments}
    slowest = sorted(changes, key=lambda c: c["committed_at"] - running[c["deployment_id"]])
    n = 0
    for c in slowest:
        if (c["committed_at"] + generate.LOCAL_OFFSET).weekday() != 4:
            break
        n += 1
    return n


ROBUST_SEEDS = range(1, 21)


def robustness() -> dict[str, str]:
    """The same model under seeds 1-20, so no conclusion rests on one random draw."""
    rows, saved, smoke_elite = [], [], 0
    for seed in ROBUST_SEEDS:
        ds = generate.simulate(seed)
        base = metrics.summarize(ds.changes, ds.deployments, ds.toil, generate.DAYS)
        ds = generate.simulate(seed, generate.Scenario(github_app=True))
        app = metrics.summarize(ds.changes, ds.deployments, ds.toil, generate.DAYS)
        ds = generate.simulate(seed, generate.Scenario(smoke_test=True))
        smoke = metrics.summarize(ds.changes, ds.deployments, ds.toil, generate.DAYS)
        rows.append(base)
        saved.append(base.lead_median - app.lead_median)
        smoke_elite += smoke.levels["failure_rate"] == "elite"

    def span(values, f) -> str:
        return f"{f(min(values))} to {f(max(values))}"

    def count(key: str, level: str) -> int:
        return sum(r.levels[key] == level for r in rows)

    n = len(rows)
    return {
        "robust_n": str(n),
        "robust_per_day": span([r.per_day for r in rows], lambda v: f"{v:.2f}"),
        "robust_freq_high": f"{count('frequency', 'high')} of {n}",
        "robust_lead": span([r.lead_median for r in rows], dur),
        "robust_lead_elite": f"{count('lead_time', 'elite')} of {n}",
        "robust_cfr": span([r.failure_rate for r in rows], pct),
        "robust_cfr_elite": f"{count('failure_rate', 'elite')} of {n}",
        "robust_smoke_elite": f"{smoke_elite} of {n}",
        "robust_recovery": span([r.recovery_median for r in rows if r.recovery_median], dur),
        "robust_recovery_elite": f"{count('recovery', 'elite')} of {n}",
        "robust_app_saved": span(saved, dur),
        "robust_app_saved_median": dur(metrics.median_td(saved)),
    }


def md_table(header: list[str], rows: list[list[str]]) -> str:
    out = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    out += ["| " + " | ".join(r) + " |" for r in rows]
    return "\n".join(out)


def build(data: Path, seed: int) -> tuple[str, dict[str, str]]:
    d = metrics.load(data)
    changes, deployments, toil = d["changes"], d["deployments"], d["toil"]
    s = metrics.summarize(changes, deployments, toil, generate.DAYS)
    levels = s.levels
    failed = [x for x in deployments if x.get("failure_cause")]

    def project(**kw) -> metrics.Summary:
        ds = generate.simulate(seed, generate.Scenario(**kw))
        return metrics.summarize(ds.changes, ds.deployments, ds.toil, generate.DAYS)

    app, app_rebase, rebase, smoke, scripted = (
        project(github_app=True),
        project(github_app=True, auto_rebase=True),
        project(auto_rebase=True),
        project(smoke_test=True),
        project(scripted_revert=True),
    )
    robust = robustness()

    stages = metrics.stage_totals(changes, deployments)
    lead_total = sum((t for _, t in stages), timedelta())
    share = {name: t / lead_total for name, t in stages}
    waiting = "Waiting for the approval click"
    approvals = sum(x["approvals"] for x in deployments)
    branch_updates = sum(x["branch_updates"] for x in deployments)
    toil_total = sum(s.toil_minutes.values())

    def toil_of(summary: metrics.Summary, kind: str) -> int:
        return summary.toil_minutes.get(kind, 0)

    paged = [x for x in failed if x["detection"] == "page"]
    ticketed = [x for x in failed if x["detection"] == "ticket"]
    revert_step = metrics.median_td([x["restored_at"] - x["responded_at"] for x in failed])
    crashes = [x for x in failed if x["failure_cause"] == "startup crash"]
    hands_on_revert = toil_of(s, "revert a failed deployment") - generate.POST_INCIDENT_MIN * len(
        failed
    )

    # Charts
    week_labels, week_counts = weekly(deployments)
    svg = {
        "deploys-per-week.svg": charts.columns(
            "Deployments per week",
            "Merged deploy pull requests per 7-day bin; the last bin is 6 days. "
            "The reference line is 7 a week, the elite boundary.",
            week_labels,
            week_counts,
            ref=(7, "7 a week: once a day, the elite boundary"),
        ),
        "lead-time-stages.svg": charts.bars(
            "Where the lead time goes",
            "Share of all commit-to-production time spent in each stage, across every change.",
            [
                (name, share[name] * 100, "--s1" if name == waiting else "--dim")
                for name, _ in stages
            ],
            fmt=lambda v: f"{v:.0f}%" if v >= 1 or v == 0 else f"{v:.1f}%",
        ),
        "lead-time-distribution.svg": charts.columns(
            "Lead time for changes",
            "Number of changes by time from commit to running in production, "
            "grouped by DORA 2024 level.",
            [label for label, _ in LEAD_BUCKETS],
            lead_histogram(s.lead_times),
            fmt=lambda v: f"{v:.0f}",
            brackets=[
                (0, 3, "elite: under a day"),
                (4, 5, "high: 1 day to 1 week"),
                (6, 6, "medium or lower"),
            ],
        ),
        "recovery.svg": charts.bars(
            "Failed deployment recovery time",
            "Minutes from the failed deployment running to the revert running, per failure. "
            "The reference line is one hour, the elite boundary.",
            [
                (
                    f"{x['deployment_id']} {x['failure_cause']}",
                    (x["restored_at"] - x["running_at"]).total_seconds() / 60,
                    "--s1" if x["detection"] == "page" else "--s2",
                )
                for x in failed
            ],
            fmt=lambda v: f"{v:.0f} min",
            refs=[(60, "1 hour")],
            legend=[("Paged (fast-burn alert)", "--s1"), ("Ticket (slow-burn alert)", "--s2")],
        ),
        "toil.svg": charts.bars(
            "Manual toil over 90 days",
            "Hours of hands-on work by kind. Merging a deploy PR is the intended human "
            "decision (ADR-0007) and is not counted.",
            [
                (kind, m / 60, "--s1" if kind == "approve held CI runs" else "--dim")
                for kind, m in s.toil_minutes.items()
            ],
            fmt=lambda v: f"{v:.1f} h",
            tick_fmt=lambda v: f"{v:g} h",
        ),
    }

    bench_rows = []
    keys = [
        (
            "frequency",
            "Deployment frequency",
            f"{s.per_day:.2f} a day ({s.deployments} in 90 days)",
        ),
        ("lead_time", "Change lead time (median)", dur(s.lead_median)),
        (
            "failure_rate",
            "Change failure rate",
            f"{pct(s.failure_rate)} ({s.failed} of {s.deployments})",
        ),
        ("recovery", "Failed deployment recovery time (median)", dur(s.recovery_median)),
    ]
    for key, name, ours in keys:
        bench_rows.append(
            [name, f"**{ours}**", f"**{levels[key]}**"] + [BENCHMARKS[lv][key] for lv in LEVELS]
        )

    values = {
        "seed": str(seed),
        "start": generate.START_LOCAL.isoformat(),
        "end": (generate.START_LOCAL + timedelta(days=generate.DAYS - 1)).isoformat(),
        "changes": str(s.changes),
        "deployments": str(s.deployments),
        "per_day": f"{s.per_day:.2f}",
        "changes_per_day": f"{s.changes / generate.DAYS:.2f}",
        "batched": str(s.changes - s.deployments),
        "max_batch": str(max(len(x["change_ids"]) for x in deployments)),
        "lead_median": dur(s.lead_median),
        "lead_p90": dur(s.lead_p90),
        "failed": str(s.failed),
        "failure_rate": pct(s.failure_rate),
        "recovery_median": dur(s.recovery_median),
        "recovery_max": dur(max(s.recoveries)),
        "lv_frequency": levels["frequency"],
        "lv_lead": levels["lead_time"],
        "lv_failure": levels["failure_rate"],
        "lv_recovery": levels["recovery"],
        "benchmark_table": md_table(
            ["Metric", "HealthQueue", "Level", "Elite", "High", "Medium", "Low"], bench_rows
        ),
        "stage_table": md_table(
            ["Stage", "Total across changes", "Share"],
            [[n, f"{t.total_seconds() / 3600:.1f} h", pct(t / lead_total)] for n, t in stages],
        ),
        "weekly_table": md_table(
            ["Week starting", *week_labels], [["Deployments", *map(str, week_counts)]]
        ),
        "lead_hist_table": md_table(
            ["Lead time", *[b for b, _ in LEAD_BUCKETS]],
            [["Changes", *map(str, lead_histogram(s.lead_times))]],
        ),
        "failure_table": md_table(
            ["Deployment", "Cause", "Detected by", "Detect", "Respond", "Revert", "Total"],
            [
                [
                    x["deployment_id"],
                    x["failure_cause"],
                    x["detection"],
                    dur(x["detected_at"] - x["running_at"]),
                    dur(x["responded_at"] - x["detected_at"]),
                    dur(x["restored_at"] - x["responded_at"]),
                    dur(x["restored_at"] - x["running_at"]),
                ]
                for x in failed
            ],
        ),
        "toil_table": md_table(
            ["Kind", "Minutes", "Share"],
            [[k, str(m), pct(m / toil_total)] for k, m in s.toil_minutes.items()],
        ),
        "toil_total": hours(toil_total),
        "share_waiting": pct(share[waiting]),
        "share_merge": pct(share["Deploy PR checks and merge"]),
        "share_sync": pct(share["Argo CD sync and rollout"]),
        "sync_hours": f"{dict(stages)['Argo CD sync and rollout'].total_seconds() / 3600:.1f} h",
        "approvals": str(approvals),
        "reapprovals": str(approvals - s.deployments),
        "approval_minutes": str(toil_of(s, "approve held CI runs")),
        "app_lead_median": dur(app.lead_median),
        "app_lead_p90": dur(app.lead_p90),
        "app_per_day": f"{app.per_day:.2f}",
        "app_deployments": str(app.deployments),
        "branch_updates": str(branch_updates),
        "update_minutes": str(toil_of(s, "update stale deploy branch")),
        "rebase_approval_minutes": str(toil_of(rebase, "approve held CI runs")),
        "rebase_extra_approval": str(
            toil_of(rebase, "approve held CI runs") - toil_of(s, "approve held CI runs")
        ),
        "app_update_minutes": str(toil_of(app, "update stale deploy branch")),
        "app_rebase_update_minutes": str(toil_of(app_rebase, "update stale deploy branch")),
        "crashes": str(len(crashes)),
        "smoke_failed": str(smoke.failed),
        "smoke_failure_rate": pct(smoke.failure_rate),
        "smoke_level": smoke.levels["failure_rate"],
        "smoke_toil_saved": str(
            toil_of(s, "revert a failed deployment") - toil_of(smoke, "revert a failed deployment")
        ),
        "paged": str(len(paged)),
        "paged_fast": str(sum(x["restored_at"] - x["running_at"] < HOUR for x in paged)),
        "ticketed": str(len(ticketed)),
        "revert_median": dur(revert_step),
        "revert_share": pct(revert_step / s.recovery_median),
        "hands_on_revert": str(hands_on_revert),
        "flake_minutes": str(toil_of(s, "rerun failed release")),
        "rotation_minutes": str(toil_of(s, "rotate kind pull secret")),
        "scripted_recovery_median": dur(scripted.recovery_median),
        "scripted_revert_minutes": str(
            toil_of(s, "revert a failed deployment")
            - toil_of(scripted, "revert a failed deployment")
        ),
        "max_week": str(max(week_counts)),
        "friday_slowest": str(friday_slowest(changes, deployments)),
        "one_failure_points": f"{100 / s.deployments:.1f}",
        **robust,
    }
    template = Template((HERE / "report_template.md").read_text(encoding="utf-8"))
    return template.substitute(values), svg


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--data", type=Path, default=HERE / "data")
    p.add_argument("--seed", type=int, default=generate.DEFAULT_SEED)
    args = p.parse_args()
    report, svg = build(args.data, args.seed)
    CHART_DIR.mkdir(parents=True, exist_ok=True)
    for name, content in svg.items():
        (CHART_DIR / name).write_text(content, encoding="utf-8", newline="\n")
    (DOCS / "dora-report.md").write_text(report, encoding="utf-8", newline="\n")
    print(f"wrote {DOCS / 'dora-report.md'} and {len(svg)} charts in {CHART_DIR}")


if __name__ == "__main__":
    main()
