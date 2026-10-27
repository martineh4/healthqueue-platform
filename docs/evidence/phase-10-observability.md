# Evidence: Phase 10, observability, SLOs and alerting

Captured 2026-10-26 on the phase 7 Codespace (`standardLinux32gb`, resumed from stopped),
Kubernetes v1.37.0 on kind. Design: [ADR-0008](../adr/0008-observability-and-slos.md),
[observability and SLOs](../observability.md). Code: PR #20, plus PR #21 for the fixes this
check found.

Sections 1 to 8 are the first check, with `main` at `e501090` (PR #20). Section 9 repeats it
after PR #21 merged, with `main` at `a8d12a4`.

## 1. Bring-up on the resumed cluster

| Step | Result |
|---|---|
| `bootstrap-cluster.sh` with `main` at `e501090` (PR #20) | Exit 0 in 78 s. It created the `grafana-admin` Secret (random password, not in Git), applied the new `monitoring` AppProject and updated the root |
| **Gap found** | The bootstrap finished with `monitoring` **OutOfSync / Healthy**: Argo CD rated the previous resources' health before it had applied `main`, and step 5 only waited for health. Fixed in PR #21, section 8 |
| 60 s later | All four applications **Synced / Healthy** at `e501090`; Prometheus, Alertmanager, Grafana, kube-state-metrics and the operator Running with 0 restarts |
| Deploy step 5 for `healthqueue-api`, run as a script | Hard refresh, wait for `status.sync.revision` = `origin/main`, rollout, Healthy. Phase 8 had only run these commands by hand |

## 2. The Helm chart renders, and Argo CD applies exactly that

`deploy/monitoring` renders kube-prometheus-stack **92.3.0** through kustomize `helmCharts`,
the same way in CI and in Argo CD (`--enable-helm`).

| Render | Objects |
|---|---|
| Argo CD, live: operation `Succeeded`, "successfully synced (all tasks run)" at `e501090` | **97** managed resources, 0 not Synced |
| Laptop: kustomize v5.8.3 + Helm v4.2.1 (CI's pinned versions), chart archive SHA-256 checked as in CI | **97** objects: 28 PrometheusRule, 23 ConfigMap, 10 ServiceMonitor, 10 CRD, 5 ServiceAccount, 5 Service, 4 ClusterRole, 4 ClusterRoleBinding, 3 Deployment, 2 Secret, 1 each of Prometheus, Alertmanager, Namespace |
| `diff` of the two `kind/name` lists | **Identical** |

CI's `manifests` check renders the same directory, validates every object with kubeconform,
requires digest-pinned images and runs the promtool tests (PR #20 and PR #21: all checks green).

## 3. Pod Security

| Namespace | Enforce | Warn / audit |
|---|---|---|
| `healthqueue` | `restricted` (v1.37) | `restricted` |
| `monitoring` | `baseline` (v1.37) | `restricted` |

**Method.** A server-side dry run of a namespace label change makes the API server check every
running pod against the new level and print a warning for each violation.

- Re-applying an identical label is a no-op and checks nothing, so the test changes
  `enforce-version` to `latest` to force an evaluation at the namespace's own level.
- Control: the same dry run on `kube-system` at `restricted` printed warnings for CoreDNS
  (`runAsNonRoot != true, seccompProfile`) and the control-plane pods. A clean result really
  is clean.

| Check | Result |
|---|---|
| `healthqueue` pods at `restricted:latest` (enforced level) | No warnings |
| `monitoring` pods at `baseline:latest` (enforced level) | No warnings |
| `monitoring` pods at `restricted` (warn/audit level) | **No warnings**: the monitoring stack meets `restricted` too, although only `baseline` is enforced |
| `FailedCreate` events in any namespace | None |
| Monitoring pods | All 5 `runAsNonRoot: true`, 0 restarts |

## 4. Prometheus scrapes the API

All 15 active targets were `up`, including:

```
healthqueue-api        up  http://10.244.0.12:8000/metrics
kube-state-metrics     up  http://10.244.0.13:8080/metrics
argocd-metrics         up  http://10.244.0.3:8082/metrics
argocd-server-metrics  up  http://10.244.0.9:8083/metrics
argocd-repo-server     up  http://10.244.0.2:8084/metrics
```

`up{job="healthqueue-api"}` = 1 for pod `healthqueue-api-7f98dc7d8b-nb5vh`. After 150 s of
`generate-traffic.sh 150 5` (about 730 requests), the last 5 minutes by route template and status:

| Route | Status | Requests |
|---|---|---|
| `/v1/appointments` | 200 / 201 / 409 | 187 / 347 / 2 |
| `/v1/appointments/{appointment_id}` | 200 / 404 | 90 / 53 |
| `/v1/providers/{provider_id}/availability` | 200 | 137 |

Labels carry route templates only, never IDs. The SLO rules evaluate on live data:

```
slo:sli_error:ratio_rate5m{slo=availability} = 0       slo:error_budget_remaining:ratio{slo=availability} = 1
slo:sli_error:ratio_rate5m{slo=latency}      = 0       slo:error_budget_remaining:ratio{slo=latency}      = 1
```

The 404 and 409 responses did not count as errors, as the SLO intends. The API's rule groups
(`healthqueue-slo-sli`, `healthqueue-slo-alerts`, `healthqueue-operations`) and the platform
`gitops` group were loaded, with **0** rule evaluation errors.

## 5. Finding: the pull-password expiry metric never existed

**Expected:** kube-state-metrics' custom-resource-state feature would export the `acr-pull`
Secret's `healthqueue.io/credential-expires-at` annotation as
`healthqueue_credential_expiry_timestamp_seconds`.

**Observed:**

- **Prometheus:** no such series. The annotation itself was present
  (`2026-11-25T04:48:13.782926+00:00`), and kube-state-metrics had RBAC to list Secrets.
- **kube-state-metrics' log at startup:**

  ```
  E1026 23:28:08.061223  1 config.go:193] "failed to resolve GVK"
    err="group is required in the defined GVK /v1, Kind=Secret" gvk="_v1_Secret"
  ```

**Root cause:** custom-resource-state metrics only support resources with an API group, in
practice CRDs. Secret is a core (group-less) resource, so kube-state-metrics v2.20.0 dropped
the configuration.

**Why CI missed it:** the chart rendered, every object passed schema validation, and the
promtool tests feed the metric in as a synthetic series. Only a running exporter could show
the gap.

**The safety net worked:** `HealthQueuePullCredentialExpiryUnknown`, which fires when the
metric is absent, was **pending** on the live cluster. Grafana's **Pull credential** panel
returned no data (section 6).

**Decision** (the maintainer's call, recorded in the ADR-0008 amendment), made in PR #21:

- removed the metric, the dashboard panel, all three expiry alerts and their tests;
- kept `create-pull-secret.sh status`, which `bootstrap-cluster.sh` runs on every start and
  which warns under 7 days;
- updated the [image-pull-failures runbook](../runbooks/image-pull-failures.md).

Production does not need any of this: on AKS the kubelet's managed identity pulls with
`AcrPull`, so there is no pull secret to expire (ADR-0004).

## 6. Grafana loads the dashboard

Through `kubectl port-forward svc/kps-grafana`, logged in as `admin` with the per-cluster
password, which was never displayed:

| Check | Result |
|---|---|
| `/api/health` | Grafana 13.2.3, database `ok` |
| Dashboard search | **HealthQueue SLOs** (`uid=healthqueue-slo`) alongside the chart's Kubernetes dashboards |
| `/api/dashboards/uid/healthqueue-slo` | 12 panels, `provisioned=true` (from `observability/dashboards/healthqueue-slo.json`) |
| Data sources | Prometheus (default, `uid=prometheus`), Alertmanager |

Every panel's query was run through Grafana's own query API (`/api/ds/query`, last 15 minutes)
against the provisioned Prometheus data source:

| Panel | Series | Panel | Series |
|---|---|---|---|
| Availability SLI | 1 | Availability burn rate | 4 |
| Availability budget left | 1 | Latency burn rate | 4 |
| Latency SLI | 1 | Requests per second by route and status | 9 |
| Latency budget left | 1 | Latency of /v1 requests | 3 |
| **Pull credential** | **0** (section 5; removed in PR #21) | Appointments per minute | 3 |
| Container restarts (1h) | 1 | What is deployed | 5 |

No query returned an error.

**From the laptop:** the [demo-day guide](../demo-day.md)'s new Grafana steps were run as
written:

- `gh codespace ports forward 8080:8080 3000:3000` forwarded both ports in one terminal.
- `http://localhost:3000/api/health` returned `ok`, and `/login` returned 200. Argo CD on
  `https://localhost:8080` returned 200 at the same time.
- The guide's Grafana password command, run in Windows PowerShell 5.1, returned a
  29-character password, which was not displayed.

## 7. Deploy PR #18 was updated in place

PR #18 was opened by `github-actions` at 04:51:59 UTC for release `c460d02`. The phase 10 merge
(`e501090`) produced a new release (run
[40276061777](https://github.com/martineh4/healthqueue-platform/actions/runs/40276061777)), and
`open-deploy-pr.sh` updated the **same** PR rather than opening a second one:

| Time (UTC) | Timeline event |
|---|---|
| 05:49:14 | `HeadRefForcePushedEvent` by `github-actions`: `c9930d4` → `0c7041e` on `deploy/prod-healthqueue-api` |
| 05:49:14 | Title renamed from "Deploy healthqueue-api c460d0289e6f to prod" to "… e50109052359 …" |

The diff is still exactly the two lines (digest
`sha256:cea7be6a…`, replacing `sha256:afc9ef49…`, and its evidence pointer). Its CI runs wait
for the maintainer's **Approve workflows to run**, as for every bot PR (ADR-0007). The PR stays
open, unapproved, for the demo.

## 8. Fixes from this check (PR #21)

| Change | Why |
|---|---|
| Expiry metric, panel, alerts and tests removed; ADR-0008 amended, with ADR-0004, the runbook and the observability guide updated | Section 5 |
| Dashboard: the four SLO tiles widened to fill the top row | The removed panel left a gap |
| `bootstrap-cluster.sh` step 5: hard-refreshes `monitoring` and waits for its sync revision = `main` and `Synced` before `Healthy` | Section 1 |
| Rule count 27 → 24; `promtool test rules` passes | Three alerts removed |

## 9. Re-check after PR #21 merged

PR #21 was rebase-merged at 00:16 UTC on 2026-10-27 (`main` at `a8d12a4`; CI and Infra green
on the push). The Codespace was stopped in between and resumed for this run. Every command
ran in the foreground.

**Bring-up.** `bootstrap-cluster.sh` exited 0 in **86 s**. With the PR #21 step 5 fix, it
waited until `monitoring` reported the `main` revision and Synced before checking health. All
four applications were **Synced / Healthy**, each with operation `Succeeded` at `a8d12a4`. The
bootstrap's own expiry check reported `token kind-pull, … (29 days left)`.

**Helm render.** Rendered in the Codespace with CI's pinned tools: kustomize v5.8.3, Helm
v4.2.1, and the chart archive, each SHA-256 checked as in CI.

| Check | Result |
|---|---|
| `kustomize build --enable-helm deploy/monitoring` | **96** objects. That is one ConfigMap fewer than section 2: the kube-state-metrics custom-resource config is gone |
| Argo CD's managed resources for `monitoring` | **96**, 0 not Synced. The `kind/name` lists are **identical** |
| Expiry metric, annotation or `customResourceState` left in the render | 0 matches |
| `promtool check rules`, then `promtool test rules` (as in CI) | 24 API rules + 2 `gitops` rules; tests **SUCCESS** |

**Pod Security.** Same method as section 3. Running pods were checked by a server-side dry run
of the namespace labels.

| Check | Result |
|---|---|
| `healthqueue` at `restricted:latest` | No warnings |
| `monitoring` at `baseline:latest` (enforced) | No warnings |
| `monitoring` at `restricted:latest` (warn/audit) | No warnings |
| Control: `kube-system` at `restricted` | Warnings for CoreDNS, the control-plane pods and kindnet |
| `FailedCreate` events | None |
| Monitoring pods | 5 Running, all `runAsNonRoot: true`. 1 restart each from the kind node restarting on resume; kube-state-metrics 0 (new pod with the new config) |

**Prometheus.** All **15/15** active targets were `up`, and `up{job="healthqueue-api"}` = 1.
Then `generate-traffic.sh 150 5` sent 730 requests (374 × 200, 313 × 201, 37 × 404, 6 × 409).
Requests in the last 5 minutes, by route template and status:

| Route | Status | Requests |
|---|---|---|
| `/v1/appointments` | 200 / 201 / 409 | 153 / 315 / 6 |
| `/v1/appointments/{appointment_id}` | 200 / 404 | 79 / 37 |
| `/v1/providers/{provider_id}/availability` | 200 | 144 |

- Both SLIs' 5-minute error ratio was `0`, and both error budgets were `1`.
- Rule groups loaded: `healthqueue-slo-sli` (19 rules), `healthqueue-slo-alerts` (4),
  `healthqueue-operations` (1), `gitops` (2). **0** rules unhealthy.

**Pull credential expiry, after the removal.**

| Check | Result |
|---|---|
| `healthqueue_credential_expiry_timestamp_seconds` series | 0, as intended |
| Rules named `*PullCredential*` | None |
| Firing or pending alerts | Only `Watchdog`, the chart's always-firing heartbeat. `HealthQueuePullCredentialExpiryUnknown` (pending in section 5) no longer exists |
| kube-state-metrics log lines mentioning GVK or custom resources | 0 (section 5 showed the startup error) |
| `create-pull-secret.sh status`, run by the bootstrap | 29 days left |

This gap is limited to kind. **Production has no pull secret:** on AKS the nodes pull with
the kubelet's managed identity, which holds `AcrPull` ([ADR-0004](../adr/0004-registry-pull-authentication.md)),
so there is no password to expire or monitor. ADR-0008's amendment records the same.

**Grafana.** Through `kubectl port-forward svc/kps-grafana`, logged in as `admin`; the
password was read into a variable and never shown.

- `/api/health`: Grafana 13.2.3, database `ok`. **HealthQueue SLOs** listed with the chart's
  dashboards.
- The dashboard has **11** panels, `provisioned=true` from `healthqueue-slo.json`. The data
  sources are Prometheus (default) and Alertmanager.
- Every panel's query was run through `/api/ds/query` over the last 15 minutes, with **no
  errors**:

| Panel | Series | Panel | Series |
|---|---|---|---|
| Availability SLI | 1 | Availability burn rate | 4 |
| Availability budget left | 1 | Latency burn rate | 4 |
| Latency SLI | 1 | Requests per second by route and status | 9 |
| Latency budget left | 1 | Latency of /v1 requests | 3 |
| Container restarts (1h) | 1 | Appointments per minute | 3 |
| What is deployed | 5 | | |

**Deploy PR #18.** PR #21 changed nothing under `app/`, so `release.yml` did not run, and no
new deploy PR was needed. PR #18 is unchanged:

- head `0c7041e`, the release of `e501090`;
- the same two-line diff;
- still the only open `deploy` PR.

GitHub now reports it `BEHIND` `main` (mergeable, no conflict). For the demo, click **Update
branch** before merging, as the [demo-day guide](../demo-day.md) troubleshooting says. It stays
open, unapproved.

**Result:** phase 10 is verified live on `main` at `a8d12a4`. The Codespace was stopped
afterwards.
