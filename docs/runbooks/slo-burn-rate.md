# Runbook: SLO error budget burn

**Alerts:**

- `HealthQueueAvailabilityBudgetBurn` and `HealthQueueLatencyBudgetBurn` (page);
- `HealthQueueAvailabilityBudgetBurnSlow` and `HealthQueueLatencyBudgetBurnSlow` (ticket).

**Background:** [observability and SLOs](../observability.md), [ADR-0008](../adr/0008-observability-and-slos.md).

## What the alert means

The API is failing its SLO fast enough to threaten the 30-day error budget:

- **Availability:** 5xx responses on `/v1`. The budget is 0.5% of requests.
- **Latency:** `/v1` requests slower than 300 ms. The budget is 1% of requests.

| Variant | Budget spent | Urgency |
|---|---|---|
| Page (fast burn) | ≥ 2% of the month's budget in an hour, or 5% in 6 hours | Act now: at this rate the budget is gone within days |
| Ticket (slow burn) | ≥ 10% in a day, or in 3 days | Fix this week: the budget will run out before the month ends |

## 1. Confirm and size it (2 minutes)

1. Open Grafana's **HealthQueue SLOs** dashboard
   ([access](../observability.md#dashboards-and-uis)). Check the burn-rate panel to see
   whether the 5m line is still high or already falling.
2. Check the **requests by route and status** panel: which route, and which status codes?
3. Or, in Prometheus:

   ```promql
   sum by (route, status) (rate(http_requests_total{namespace="healthqueue", status=~"5.."}[5m]))
   histogram_quantile(0.99, sum by (le, route) (rate(http_request_duration_seconds_bucket{namespace="healthqueue"}[5m])))
   ```

If the short window has already recovered, the alert clears within minutes. Still record
the budget spent (step 4).

## 2. Did something just change? (most common cause)

```bash
gh pr list --repo martineh4/healthqueue-platform --state merged --limit 5   # recent merges
kubectl -n argocd get application healthqueue-api -o jsonpath='{.status.sync.revision}{"\n"}'
kubectl -n healthqueue get pods -o wide
```

**If the burn started with a deploy, roll back first and investigate after.** Revert the
deploy PR's merge commit (GitHub's **Revert** button opens the PR), merge it, then click
**Refresh** in Argo CD ([ADR-0007](../adr/0007-pr-driven-image-promotion.md)).

## 3. Diagnose

Logs carry the route, status, duration and request ID, and never request bodies:

```bash
kubectl -n healthqueue logs deploy/healthqueue-api --since=15m | grep -E '"status": 5[0-9]{2}' | tail -20
kubectl -n healthqueue logs deploy/healthqueue-api --since=15m | grep -i '"level": "ERROR"' | tail -20
```

| Pattern | Likely cause | Action |
|---|---|---|
| 5xx on every `/v1` route, `/readyz` returning 503 | Database unavailable: volume full, file locked, PVC problem | `kubectl -n healthqueue describe pod`; check the PVC and free space; see ADR-0005 |
| 5xx on one route only | Bug in that code path | Roll back (step 2); open an issue with the request IDs |
| Latency only, all routes | CPU throttling or the node under load | `kubectl top pod -n healthqueue` (if metrics-server is installed); check the Deployment's CPU limit |
| Latency only, one route | Slow query, e.g. a growing appointment table without an index | Profile; add an index in a pull request |
| Burn during a deploy or restart only | Recreate strategy downtime (single replica, ADR-0005) | Expected and small. If deploys alone page, the objective or the architecture needs revisiting |

## 4. Afterwards

- Note the budget spent: the dashboard's **budget left** panels, or the
  `slo:error_budget_remaining:ratio` series.
- Apply the [error budget policy](../observability.md#error-budget-policy).
- For pages, write a short incident review: timeline, detection (did the alert fire early
  enough?), cause, follow-ups.
