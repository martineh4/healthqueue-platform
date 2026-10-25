# Evidence: Phase 6, hardened manifests and pull-only registry token

Captured 2026-10-25. Design: [ADR-0004](../adr/0004-registry-pull-authentication.md),
[ADR-0005](../adr/0005-sqlite-single-replica-data-store.md), [`deploy/`](../../deploy/README.md).

## 1. Manifest checks (PR #9)

The `manifests` job (now a required check) passed:

- **kustomize v5.8.3 and kubeconform v0.8.0:** downloaded and verified against SHA-256 sums
  recorded in the workflow.
- **`kubeconform -strict`:** passed against the Kubernetes 1.37.0 schemas.
- **Digest pinning:** every `image:` uses `@sha256:`.
- **Trivy config scan of the rendered output:** 0 HIGH/CRITICAL.

Trivy v0.75.0, run locally on the same rendered output, found 0 HIGH/CRITICAL. Its one MEDIUM
finding is a false positive: KSV-01010 flags `HQ_LOG_LEVEL` as "sensitive" because of its name.

Rendered checks inspected by hand:
- `default-deny-all` keeps `podSelector: {}`, so it still selects every pod; the
  `includeSelectors` labels did not narrow it.
- The ingress policy admits only `namespaceSelector kubernetes.io/metadata.name=monitoring`.
- The Deployment selector holds only the stable `name` and `component` labels.

## 2. Token created through the PR flow

The PR plan comment read `Plan: 2 to add, 0 to change, 0 to destroy`: scope map
`healthqueue-api-pull` and token `kind-pull`. After merge, `tofu-apply` succeeded as the CI apply
identity.

## 3. Proof the token is pull-only

A password with a 1-day expiry was minted and held only in a shell variable, never printed. It
was used against ACR's token endpoint, which returns the permissions actually granted, and then
**deleted**.

| Request | Granted |
|---|---|
| `repository:healthqueue-api:pull,push,delete` | `pull` only |
| `repository:some-other-repo:pull` | nothing |
| `registry:catalog:*` | `limited` (ACR's minimum; lists only repositories in scope) |

With the pull-scoped access token:

| Call | Result |
|---|---|
| `GET /v2/healthqueue-api/manifests/sha256:4699…59f5` (the deployed digest) | `200` |
| `GET /v2/healthqueue-api/referrers/sha256:4699…59f5` (signatures and attestations) | `200` |

Afterwards: `az acr token show … --query length(credentials.passwords)` → `0`. The token holds no
password until a cluster needs one.

## 4. Bug found by the test, and fixed

The first test showed an empty expiry. With `-o tsv`, the Azure CLI prints each element of
`[value, expiry]` on its **own line**, so `read -r password expiry` captured only the password.
`create-pull-secret.sh` treats a missing expiry as failure, so it would have exited every time.
The fix reads two lines (`{ read -r password; read -r expiry; }`). It was tested against ACR with
a 1-day password, which was deleted afterwards. `status` parses the returned timestamp format
(`2026-10-26T07:42:43.757666+00:00`) correctly with GNU `date`.

## 5. Not yet demonstrated (phase 7, in the Codespace)

- Running `create-pull-secret.sh` end to end against a live cluster, including server-side apply
  and the `status` output
- Pods admitted under the `restricted` Pod Security Standard and pulling the signed image
- NetworkPolicy enforcement and probe behaviour on kind
