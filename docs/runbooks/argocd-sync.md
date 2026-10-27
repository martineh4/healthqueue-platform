# Runbook: Argo CD application out of sync or degraded

**Alerts:**

- `ArgoCDApplicationOutOfSync` (ticket): the application has not matched `main` for 15
  minutes;
- `ArgoCDApplicationDegraded` (ticket): its resources have been Degraded or Missing for
  10 minutes.

**Background:** [ADR-0006](../adr/0006-gitops-with-argo-cd.md); the application's
`name` label says which one.

## 1. Look at the application (2 minutes)

Open the Argo CD UI ([demo-day guide, step 4](../demo-day.md#4-open-argo-cd-and-grafana-in-your-browser))
and select the application, or:

```bash
kubectl -n argocd get applications
kubectl -n argocd get application <name> -o jsonpath='{.status.conditions}{"\n"}{.status.operationState.message}{"\n"}'
```

## 2. Out of sync

| Message | Cause | Fix |
|---|---|---|
| `... is not permitted in project ...` | A merged manifest uses a kind or namespace its AppProject does not allow (`deploy/argocd/projects/`) | Intended: extend the project in a pull request. Not intended: revert the change |
| `the server could not find the requested resource` / no matches for kind | A custom resource whose CRD is not installed yet (e.g. `ServiceMonitor` before the monitoring stack) | Usually resolves on retry once the CRD exists; if not, check the `monitoring` application |
| Validation or `field is immutable` errors | Invalid manifest, or a change Kubernetes cannot apply in place (e.g. a Deployment selector) | Fix in a pull request; for immutable fields, delete the object deliberately, then sync |
| `ComparisonError`, repository errors | Argo CD cannot read or render the repository | `kubectl -n argocd logs deploy/argocd-repo-server --tail=50`; check GitHub status and the kustomize render (`kustomize build --enable-helm <path>`) |
| Stays `OutOfSync` with no error, auto-sync idle | Auto-sync retries exhausted | Fix the cause, then click **Sync**, or `kubectl -n argocd annotate application <name> argocd.argoproj.io/refresh=hard --overwrite` |

CI's `manifests` check renders and validates every kustomization before merge. A sync
failure that CI did not catch is a gap worth closing in CI.

## 3. Degraded or Missing

Open the resource tree in the UI and find the red resource; its events usually say why.

| Resource | Next step |
|---|---|
| A HealthQueue pod | [api-unavailable](api-unavailable.md) or [image pull failures](image-pull-failures.md) |
| A monitoring pod | `kubectl -n monitoring describe pod <pod>`; PodSecurity rejections show as `FailedCreate` events on the ReplicaSet or StatefulSet |
| `Missing` | Created outside Argo CD and deleted, or pruned. A sync recreates it |

## Afterwards

Argo CD's history (the application's **History and rollback** tab) shows which revision
synced when. Note the time to recovery: a DORA analysis of real deployments would use it
(the [DORA report](../dora-report.md) explains how to run one; phase 11 used synthetic data).
