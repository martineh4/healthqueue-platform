# Runbook: image pull failures (`ImagePullBackOff`, `ErrImagePull`)

**Applies to:** the `healthqueue` namespace on the kind cluster.
**Background:** [ADR-0004](../adr/0004-registry-pull-authentication.md).

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

- If the cause was an expired credential, note how many days of warning `status` gave. Phase 10
  alerts on the expiry annotation.
- Record the incident duration. It counts against the availability SLO.
