# Runbook: HealthQueue API unavailable

**Alert:** `HealthQueueAPIUnavailable` (page). Prometheus has had no successful scrape of the
API for 5 minutes.

**Background:** single replica with Recreate deploys (ADR-0005), managed by Argo CD
(ADR-0006).

## 1. Is there a pod, and what state is it in? (1 minute)

```bash
kubectl -n healthqueue get deploy,pods -o wide
kubectl -n argocd get application healthqueue-api
```

| What you see | Go to |
|---|---|
| No pod, Deployment `0/0` | Someone scaled it down. Argo CD's self-heal restores it within seconds; if not, check the application's sync status (Argo CD may be down) |
| `ImagePullBackOff`, `ErrImagePull` | [image pull failures](image-pull-failures.md) |
| `CrashLoopBackOff` | Step 2 |
| `Pending` | Step 3 |
| `Running` but not `Ready` | Step 4 |
| `Running` and `Ready` | Step 5: the pod is fine and Prometheus cannot reach it |

## 2. Crash loop

```bash
kubectl -n healthqueue logs deploy/healthqueue-api --previous | tail -30
kubectl -n healthqueue describe pod -l app.kubernetes.io/name=healthqueue-api | sed -n '/Last State/,/Ready/p'
```

- **A Python traceback at startup:** a bad release or a bad configuration change. Revert the
  last deploy or config pull request.
- **`OOMKilled`:** raise the memory limit in `deploy/base/deployment.yaml` through a pull
  request; investigate the growth.
- **Database errors:** check the PVC (`kubectl -n healthqueue get pvc`) and free space in the
  volume.

## 3. Pending

```bash
kubectl -n healthqueue describe pod -l app.kubernetes.io/name=healthqueue-api | sed -n '/Events:/,$p'
```

A PVC that won't bind, or insufficient resources on the single kind node, are the usual
causes. `kubectl get nodes` should show the node `Ready`. On a resumed Codespace, re-run
`deploy/scripts/bootstrap-cluster.sh`.

## 4. Running but not ready

`/readyz` returns 503 when the database can't be reached. Logs show `readiness check
failed` with the exception.

## 5. Healthy pod, failing scrape

```bash
kubectl -n monitoring port-forward svc/kps-prometheus 9090:9090   # then open Status > Targets
kubectl -n healthqueue get networkpolicy healthqueue-api-ingress -o yaml
```

The API admits traffic only from the `monitoring` namespace (`deploy/base/networkpolicy.yaml`).
A change to that policy, or to the `monitoring` namespace's name or labels, makes the scrape
fail while the service itself is fine. Fix the policy through a pull request.

## Afterwards

Unavailability burns the availability budget at full speed. Expect the burn-rate alerts too,
and follow [slo-burn-rate](slo-burn-rate.md#4-afterwards).
