# Runbook: image pull failures (`ImagePullBackOff`, `ErrImagePull`)

**Applies to:** the `healthqueue` namespace on the kind cluster.
**Background:** [ADR-0004](../adr/0004-registry-pull-authentication.md).

## How you get here

- **`HealthQueueAPIUnavailable` (page):** a new pod could not pull its image, so after a
  Recreate rollout no pod is serving. The [api-unavailable](api-unavailable.md) runbook sends
  you here when the pod shows `ImagePullBackOff`.
- **`ArgoCDApplicationDegraded` (ticket):** the same failure, seen from Argo CD.
- **`warning: rotate soon`** from `bootstrap-cluster.sh`: the password expires in under 7 days.
  Rotate it now (step 2), before anything fails.

### Checking the password's expiry

There is no expiry alert: kube-state-metrics cannot turn a Secret's annotation into a metric
(ADR-0008). Check the days left with:

```bash
deploy/scripts/create-pull-secret.sh status
```

It reads the `healthqueue.io/credential-expires-at` annotation that the script writes on every
rotation. `bootstrap-cluster.sh` runs it on every start and warns under 7 days. To rotate from a
workstation without an Azure login in the Codespace, pipe a new password in with
`create-pull-secret.sh --stdin`; the [demo-day guide](../demo-day.md), step 2, has the exact
command.

On AKS this whole failure mode goes away: the kubelet's managed identity pulls with `AcrPull`,
and there is no password to expire (ADR-0004).

## Symptoms

- `kubectl get pods -n healthqueue` shows `ImagePullBackOff` or `ErrImagePull`.
- Argo CD shows the application as *Progressing* or *Degraded* after a sync.
- Pods that were already running are usually **unaffected**, because the image is cached on the
  node. The failure appears when a pod is created or rescheduled.

## 1. Read the actual error (2 minutes)

```bash
kubectl describe pod -n healthqueue -l app.kubernetes.io/name=healthqueue-api | sed -n '/Events:/,$p'
```

| Message contains | Likely cause | Go to |
|---|---|---|
| `401 Unauthorized`, `unauthorized: authentication required` | Pull secret missing, expired or revoked | Step 2 |
| `secret "acr-pull" not found` (in events or `kubectl get events`) | Pull secret never created on this cluster | Step 3 |
| `403 Forbidden`, `denied: requested access to the resource is denied` | Token scope does not cover the repository | Step 4 |
| `manifest unknown`, `not found` | The digest in the overlay does not exist in ACR | Step 5 |
| `dial tcp`, `i/o timeout`, `no such host` | Network or DNS from the node to ACR | Step 6 |

## 2. Expired or revoked credential

```bash
deploy/scripts/create-pull-secret.sh status
```

- **Expired, or less than 7 days left:** rotate by running
  `deploy/scripts/create-pull-secret.sh`.
- **Not expired:** check that the token is enabled:

  ```bash
  az acr token show -r crhealthqueueora3w -n kind-pull --query status -o tsv
  ```

  `disabled` means someone revoked it. Find out why (activity log, recent PRs to
  `infra/envs/prod`) **before** re-enabling it. If the revocation was a security response, do not
  undo it; escalate.

After rotating, make Kubernetes retry straight away instead of waiting for the back-off:

```bash
kubectl delete pod -n healthqueue -l app.kubernetes.io/name=healthqueue-api
```

## 3. Secret missing on a new cluster

This is expected on a freshly created kind cluster. Run `deploy/scripts/create-pull-secret.sh`,
then delete the failing pod as in step 2.

## 4. Scope problem

The token can only read `healthqueue-api`. If a new image or repository was introduced, its
scope must be added to `azurerm_container_registry_scope_map.api_pull` in `infra/envs/prod`
through a pull request. Do not switch to the admin user or a broader token as a shortcut.

## 5. Digest not found

```bash
kubectl kustomize deploy/overlays/prod | grep image:
az acr manifest list-metadata -r crhealthqueueora3w -n healthqueue-api --query "[].digest" -o tsv
```

If the overlay points at a digest that was never pushed, the release that should have produced
it failed. Check the `Release` workflow run for that commit. Fix forward by pointing the overlay
at the last good digest from `release-evidence/`; never point it at a tag.

## 6. Network

From inside the Codespace:

```bash
docker exec healthqueue-control-plane curl -sI https://crhealthqueueora3w.azurecr.io/v2/
```

A `401` response means the registry is reachable and the problem is credentials (step 2). A
timeout or DNS error points at the Codespace's network or an Azure outage; check
https://azure.status.microsoft.

## Afterwards

- If the cause was an expired credential, find out why it was not rotated. The only warning is
  `bootstrap-cluster.sh`'s "rotate soon" under 7 days, so a cluster left running for weeks
  without a bootstrap gets none. Put the expiry date in the team calendar when rotating.
- Record the incident duration. It counts against the availability SLO.
