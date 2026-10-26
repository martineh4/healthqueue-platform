# ADR-0008: Observability stack and SLO-based alerting

- **Status:** Accepted
- **Date:** 2026-10-26
- **Deciders:** Platform engineering; informed: CTO
- **Related:** [observability and SLOs](../observability.md), [ADR-0005](0005-sqlite-single-replica-data-store.md),
  [ADR-0006](0006-gitops-with-argo-cd.md), [ADR-0004](0004-registry-pull-authentication.md)

## Context

The API already emits Prometheus metrics: request counts and latency by route template, plus
business counters. It writes structured JSON logs without PHI. Nothing collects them yet,
there are no service level objectives, and nothing alerts. Two operational risks are known
to fail silently:

- The single replica (ADR-0005) can be down without anyone noticing.
- The registry pull password expires (ADR-0004), and the cluster would only notice at the next
  image pull, possibly during an incident.

Requirements:

1. **SLOs that match the architecture,** with alerts on error-budget burn rather than on raw
   thresholds, which page too often or too late.
2. **Monitoring as code:** rules, alerts and dashboards reviewed in pull requests, deployed by
   Argo CD, and **tested in CI** like application code.
3. **The service owns its SLOs:** they are versioned and deployed with the service, not in a
   central config.
4. **Same supply-chain bar as everything else:** pinned chart, digest-pinned images, and CI
   validating exactly what will be applied.
5. **No secrets in Git,** including dashboard logins.

## Decision

### Stack: kube-prometheus-stack, rendered by kustomize

- **What:** Prometheus Operator, Prometheus, Alertmanager, Grafana and kube-state-metrics,
  from the community chart **92.3.0**, in a `monitoring` namespace. A new `monitoring`
  AppProject limits it to that namespace, its CRDs and its read-only cluster RBAC.
- **Rendering:** `deploy/monitoring` renders the chart with kustomize `helmCharts`, and Argo CD
  runs kustomize with `--enable-helm` (set in `argocd-cm` through `deploy/argocd/install`).
  CI's `manifests` check renders the same directory with the same Helm version as Argo CD
  (4.2.1), after verifying the chart archive's SHA-256. kubeconform validates every object,
  including the operator's custom resources.
- **Digest pinning:** every image is pinned by digest through the chart's `sha` values,
  including images the operator receives as flags (config reloader, Thanos default). CI's
  digest check now also inspects those flags; that check found the unpinned Thanos default
  during this phase.
- **Left out on kind:** node-exporter (needs host access, and the "node" is a container),
  etcd, scheduler, controller manager, kube-proxy and CoreDNS scraping (bound to localhost
  inside kind, or outside the `monitoring` namespace), and the operator's admission webhook
  (`promtool` validates rules in CI instead).
- **Pod Security:** `monitoring` enforces `baseline` and warns and audits on `restricted`;
  the application namespace enforces `restricted`.

### SLOs and alerts live with the service

`observability/` holds the API's ServiceMonitor, its PrometheusRule (SLIs, budget, alerts)
and its Grafana dashboard. `deploy/overlays/prod` includes it, so the `healthqueue-api`
Application deploys the SLOs with the code they describe. The `healthqueue` AppProject now
allows `ServiceMonitor` and `PrometheusRule`, and nothing else new.

- **SLOs:** **availability 99.5%** (non-5xx `/v1` responses) and **latency 99% ≤ 300 ms**, over
  30 days. Rationale is in [observability.md](../observability.md). In short, 99.5% is what one
  SQLite replica with Recreate deploys can honestly keep; ADR-0005's PostgreSQL path is what
  raises it.
- **Recording rules:** error ratios over 5m, 30m, 1h, 2h, 6h, 1d, 3d and 30d, plus the
  objective and the remaining budget as series. Dashboards and alerts read the same numbers.
- **Alerts:** multiwindow, multi-burn-rate (Google SRE workbook):
  - **page** at 14.4× (1h and 5m) or 6× (6h and 30m);
  - **ticket** at 3× (1d and 2h) or 1× (3d and 6h).

  Each alert has a runbook link.
- **Operations alerts:**
  - API unavailable for 5 minutes;
  - pull credential expiring in under 7 days (ticket) or 1 day (page);
  - pull credential expiry not reported (ticket);
  - Argo CD application out of sync for 15 minutes, or degraded for 10 minutes.
- **Tests:** `observability/tests/slo.test.yaml` runs the real rules against synthetic
  series with `promtool test rules` in CI. During development, a deliberately wrong threshold
  made the tests fail, so they do catch regressions.

### Pull credential expiry without reading the secret

`create-pull-secret.sh` already writes the expiry into the Secret's
`healthqueue.io/credential-expires-at` annotation. kube-state-metrics' custom-resource-state
feature exports that annotation as `healthqueue_credential_expiry_timestamp_seconds`. Only
metadata is used, and no new workload or permission is added: kube-state-metrics already
watches Secrets.

### Secrets

Grafana's admin password is generated per cluster by `bootstrap-cluster.sh`, the same
pattern as the pull secret. Argo CD does not manage that Secret. The chart's own option would
have generated a new random password on every render, leaving Argo CD permanently out of
sync.

## Consequences

**Positive**

- Pages mean a real, sustained threat to the SLO, and each one links to a runbook.
- The pull credential no longer expires silently.
- Alert logic has unit tests, so a broken threshold fails the pull request instead of the
  next incident.
- Monitoring changes follow the same path as everything else: pull request, CI, merge, then
  Argo CD.

**Negative / accepted risks**

- **The chart is pinned by version, not by content, at sync time.** CI verifies the archive's
  checksum before rendering, but Argo CD downloads the chart again by version. A
  republished chart version could differ from what CI checked. Mitigations: images are
  digest-pinned, so a changed chart cannot silently change images without failing the next
  CI render, and drift would show as an Argo CD diff. Vendoring the chart, or an OCI
  reference by digest, would close this.
- **No persistence on kind.** Prometheus uses an emptyDir, so the 30-day SLI resets when the
  pod restarts.
- **The Grafana admin password is a manual-bootstrap secret,** like the pull secret.
  Production uses SSO.
- **No NetworkPolicies in `monitoring`.** Its pods can reach anything. The API's namespace is
  protected and admits only `monitoring`.
- **Low traffic exaggerates ratios.** With a handful of requests, one 5xx can exceed the
  14.4× threshold. Production would add a minimum-traffic condition, or use synthetic traffic
  to keep the denominator meaningful.

## Alternatives considered

| Option | Why rejected |
|---|---|
| Azure Monitor managed Prometheus + Managed Grafana | The production path on AKS. It cannot scrape a kind cluster inside a Codespace without an agent and outbound credentials, and its cost would come out of the Azure for Students budget. |
| Argo CD Helm source instead of kustomize `helmCharts` | CI would need a separate `helm template` invocation, and the "CI validates exactly what Argo CD applies" property would depend on keeping two renderings in sync. |
| Sloth or Pyrra to generate SLO rules | Adds a generator (and, for Pyrra, an operator) to explain and pin. The generated rules are about 30 lines of repetitive PromQL, written out and tested directly here. |
| Threshold alerts (error rate > 1% for 5m) | Page on short blips that barely touch the budget, and miss slow burns that exhaust it. |
| A CronJob to check the pull secret's expiry | Needs an image, RBAC to read the Secret (including its data), and a way to raise alerts. kube-state-metrics reads only the annotation. |

## Revisit when

- **The cluster moves to AKS:** evaluate Azure Monitor managed Prometheus; add persistence
  and real receivers.
- **Traffic is low enough that ratios mislead:** add a minimum-traffic guard to the
  burn-rate alerts.
- **The API gains replicas (PostgreSQL):** raise the availability objective, and switch
  deploys to rolling updates.
