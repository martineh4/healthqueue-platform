# Kubernetes deployment

```
deploy/
├── base/                 # environment-neutral manifests (not deployable alone)
├── overlays/
│   └── prod/             # namespace, labels, image pinned by digest; Argo CD syncs this
└── scripts/
    └── create-pull-secret.sh   # pull-only, expiring registry credential (ADR-0004)
```

Render and inspect what Argo CD will apply:

```bash
kubectl kustomize deploy/overlays/prod
```

## What is in the base

| Object | Notes |
|---|---|
| `Deployment healthqueue-api` | 1 replica, `Recreate` (SQLite, [ADR-0005](../docs/adr/0005-sqlite-single-replica-data-store.md)). Non-root UID 10001, read-only root filesystem, all capabilities dropped, seccomp `RuntimeDefault`, no ServiceAccount token. Startup, liveness (`/healthz`) and readiness (`/readyz`, checks the database) probes |
| `ConfigMap healthqueue-api-config-<hash>` | `HQ_*` settings. The hash suffix makes any change roll the pod |
| `PersistentVolumeClaim healthqueue-data` | 1 GiB `ReadWriteOnce`, holds `/data/healthqueue.db` |
| `Service healthqueue-api` | ClusterIP, port 80 → `http` (8000) |
| `ServiceAccount healthqueue-api` | `imagePullSecrets: acr-pull`, created out of band, never in Git |
| `NetworkPolicy` × 2 | Default deny in and out for the namespace; the API accepts traffic only from the `monitoring` namespace and has no egress |

The `prod` overlay adds the `healthqueue` namespace. The namespace **enforces the `restricted`
Pod Security Standard**, so any pod that is not hardened as above is rejected at admission.

## Checks on every pull request (`manifests` job in `ci.yml`)

1. `kustomize build` for every overlay (kustomize v5.8.3, checksum-verified).
2. `kubeconform -strict` against the Kubernetes 1.37 schemas, the same version as the kind node
   image.
3. Every `image:` must be pinned by `@sha256:` digest.
4. Trivy misconfiguration scan of the **rendered** output (HIGH and CRITICAL fail the build).

## First deploy on a new cluster

Phase 7 automates the sync with Argo CD. The pull secret is always created by hand, because it
is the one thing that must never come from Git:

```bash
az login                                   # an identity that can generate ACR token passwords
deploy/scripts/create-pull-secret.sh       # 30-day password, straight into the cluster
deploy/scripts/create-pull-secret.sh status
kubectl apply -k deploy/overlays/prod      # until Argo CD takes over in phase 7
kubectl -n healthqueue port-forward svc/healthqueue-api 8000:80
```

Pull failures: [runbook](../docs/runbooks/image-pull-failures.md).

## Changing the deployed version

Never edit a tag in. The release workflow prints the digest and records it in
`release-evidence/` along with its signature and attestations. Update `digest:` in
`overlays/prod/kustomization.yaml` through a pull request (phase 8 automates this):

```bash
cd deploy/overlays/prod
kustomize edit set image healthqueue-api=crhealthqueueora3w.azurecr.io/healthqueue-api@sha256:<digest>
```
