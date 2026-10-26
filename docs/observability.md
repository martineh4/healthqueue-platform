# Observability and SLOs

How the HealthQueue API is measured, what it promises, and who gets woken up when the promise
is at risk.

- **Design:** [ADR-0008](adr/0008-observability-and-slos.md).
- **Code:** [`observability/`](../observability/) (scrape config, SLO rules, alerts,
  dashboard) and [`deploy/monitoring/`](../deploy/monitoring/) (the monitoring stack).

## Service level objectives

Both are measured over a rolling 30-day window, on `/v1` API requests only. Health checks,
`/metrics` and unknown paths are excluded.

| SLO | SLI (good events / valid events) | Objective | Error budget (30 days) |
|---|---|---|---|
| **Availability** | Requests that did not return 5xx / all `/v1` requests | **99.5%** | 0.5% of requests, about 3.6 hours of total outage |
| **Latency** | Requests served in ≤ 300 ms / all `/v1` requests | **99%** | 1% of requests may be slower |

Why these numbers:

- **99.5%, not higher:** the API runs as one replica on SQLite (ADR-0005). Every deploy and
  node restart is a few seconds of downtime, and a promise this architecture can't keep would
  just generate noise.
- **Raising it:** ADR-0005's PostgreSQL path, with several replicas and rolling updates, is
  the prerequisite.
- **300 ms:** a booking is an interactive form submission. The histogram has a bucket exactly
  at 0.3 s, so the SLI comes from bucket counts with no estimation.

What does **not** count against the budget:

- 4xx responses: validation errors (422), a slot already taken (409), unknown appointment
  (404). These are correct answers.
- Requests that never reach the pod, such as cluster networking failures. Those would need a
  synthetic probe, which is listed under gaps below.

## Error budget policy

| Budget left (30 days) | What the team does |
|---|---|
| > 50% | Ship normally. |
| 25–50% | Review recent incidents; prefer reliability fixes in the next pull requests. |
| < 25% | Deploys limited to fixes and low-risk changes until the budget recovers. |
| Exhausted (≤ 0%) | Feature releases stop; the next work is the top reliability item from the incident reviews. |

The dashboard's **budget left** panels show where the team stands; `slo:error_budget_remaining:ratio`
holds the same number for automation.

## Alerts

Burn rate is how fast the budget is being spent. 1× spends exactly the budget in 30 days;
14.4× spends 2% of it in one hour. Each burn-rate alert needs a long window, which proves
the burn is real, and a short window, which clears the alert soon after recovery
(multiwindow, multi-burn-rate; Google SRE workbook, chapter 5).

| Alert | Fires when | Severity | Runbook |
|---|---|---|---|
| `HealthQueueAvailabilityBudgetBurn` | Error ratio > 14.4× budget over 1h **and** 5m, or > 6× over 6h **and** 30m, for 2m | **page** | [slo-burn-rate](runbooks/slo-burn-rate.md) |
| `HealthQueueAvailabilityBudgetBurnSlow` | > 3× over 1d and 2h, or > 1× over 3d and 6h, for 15m | ticket | [slo-burn-rate](runbooks/slo-burn-rate.md) |
| `HealthQueueLatencyBudgetBurn` | Same thresholds, latency SLI | **page** | [slo-burn-rate](runbooks/slo-burn-rate.md) |
| `HealthQueueLatencyBudgetBurnSlow` | Same thresholds, latency SLI | ticket | [slo-burn-rate](runbooks/slo-burn-rate.md) |
| `HealthQueueAPIUnavailable` | No successful scrape of the API for 5 minutes | **page** | [api-unavailable](runbooks/api-unavailable.md) |
| `HealthQueuePullCredentialExpiringSoon` | Registry pull password expires in < 7 days | ticket | [image-pull-failures](runbooks/image-pull-failures.md) |
| `HealthQueuePullCredentialExpiring` | Expires in < 1 day, or has expired | **page** | [image-pull-failures](runbooks/image-pull-failures.md) |
| `HealthQueuePullCredentialExpiryUnknown` | No expiry metric for 30 minutes (secret, annotation or exporter missing) | ticket | [image-pull-failures](runbooks/image-pull-failures.md) |
| `ArgoCDApplicationOutOfSync` | An Argo CD application has not matched `main` for 15 minutes | ticket | [argocd-sync](runbooks/argocd-sync.md) |
| `ArgoCDApplicationDegraded` | An application's resources Degraded or Missing for 10 minutes | ticket | [argocd-sync](runbooks/argocd-sync.md) |

**Routing:** `page` and `critical` alerts page the on-call engineer, and `ticket` and
`warning` alerts open a ticket. A page inhibits the ticket for the same SLO. On kind the
receivers are placeholders, so alerts appear in the Prometheus and Alertmanager UIs only.
Production wires `page` to the paging tool and `ticket` to the team's queue.

kube-prometheus-stack's default Kubernetes rules (crash-looping pods, failing Deployments,
Prometheus and Alertmanager self-monitoring) are also active, minus those for components
kind does not expose.

**The rules are tested.** [`observability/tests/slo.test.yaml`](../observability/tests/slo.test.yaml)
feeds synthetic metrics through the real rules, and CI's `manifests` check runs
`promtool test rules`. The tests cover:

- healthy traffic stays silent;
- a 50% outage after hours of healthy traffic pages within 10 minutes, but not in the first
  minute;
- a 4× burn sustained for a day opens a ticket but never pages;
- slow responses page;
- the API disappearing pages after 5 minutes;
- a pull credential with 6 days left raises a ticket, not a page;
- a missing expiry metric raises a ticket;
- an Argo CD application stuck out of sync raises a ticket.

## Signals

| Signal | Source | Notes |
|---|---|---|
| `http_requests_total{method, route, status}` | The API | `route` is the route template (`/v1/appointments/{appointment_id}`), never the raw path: bounded cardinality, no IDs in metrics |
| `http_request_duration_seconds` | The API | Buckets 25 ms … 5 s, with one at the 300 ms SLO threshold |
| `healthqueue_appointments_booked_total`, `_booking_conflicts_total`, `_appointments_cancelled_total` | The API | Business events |
| `healthqueue_credential_expiry_timestamp_seconds` | kube-state-metrics, read from the `acr-pull` Secret's `healthqueue.io/credential-expires-at` annotation | Written by `create-pull-secret.sh`; no secret data is read |
| `argocd_app_info{sync_status, health_status}` | Argo CD | Delivery health; also used for DORA (phase 11) |
| Kubernetes object state | kube-state-metrics | Restarts, replicas, image of each pod |
| Logs | The API, JSON on stdout | Request ID, route template, status, duration. No bodies or query strings, which may hold PHI. Read with `kubectl logs`; a log store is out of scope on kind |

## Dashboards and UIs

**HealthQueue SLOs** (Grafana, provisioned from
[`observability/dashboards/healthqueue-slo.json`](../observability/dashboards/healthqueue-slo.json)):

- the SLI and budget left for both SLOs;
- days until the pull credential expires;
- burn rate per window, with the paging thresholds marked;
- requests by route and status, and latency percentiles;
- business events and container restarts;
- the running image digest and the state of every Argo CD application.

Dashboards are code: edit the JSON in a pull request. UI edits are not saved.

From a Codespace shell (or with `gh codespace ports forward`, as in the
[demo-day guide](demo-day.md)):

```bash
kubectl -n monitoring port-forward svc/kps-grafana 3000:80            # http://localhost:3000
kubectl -n monitoring get secret grafana-admin -o jsonpath='{.data.admin-password}' | base64 -d
kubectl -n monitoring port-forward svc/kps-prometheus 9090:9090       # Prometheus: Alerts, Rules, Targets
kubectl -n monitoring port-forward svc/kps-alertmanager 9093:9093     # Alertmanager
deploy/scripts/generate-traffic.sh 600 5                              # 10 minutes of demo traffic
```

The Grafana user is `admin`. `bootstrap-cluster.sh` generates the password per cluster;
it is never in Git.

## Gaps and production differences

| Here (kind) | Production |
|---|---|
| Prometheus storage is an emptyDir, so history is lost when the pod restarts and the 30-day SLI only covers data since then | Persistent volume, or Azure Monitor managed Prometheus with long-term storage |
| Alert receivers are placeholders | Paging and ticketing integrations; alerts link to these runbooks |
| No synthetic probe: requests that never reach the pod are invisible to the SLI | Blackbox probe from outside the cluster, measured as its own SLI |
| No log store | Logs shipped to Log Analytics / Loki, queried by request ID |
| No tracing | OpenTelemetry once the API calls other services (today it calls none) |
| Grafana admin login | SSO (Entra ID) with viewer and editor groups |
| `monitoring` namespace has no NetworkPolicies (the API's namespace does) | Default-deny there too, with Prometheus egress allowed to scrape targets and the API server |
