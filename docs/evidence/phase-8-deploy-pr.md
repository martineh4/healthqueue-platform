# Evidence: Phase 8, PR-driven image promotion

Captured 2026-10-26. Design: [ADR-0007](../adr/0007-pr-driven-image-promotion.md),
[`open-deploy-pr.sh`](../../.github/scripts/open-deploy-pr.sh). Demo procedure:
[demo-day guide](../demo-day.md).

## 1. End-to-end timeline

| Time (UTC) | Event |
|---|---|
| 04:01:24 | PR #15 merged (phase 8 itself, including the new `/version` endpoint) |
| 04:01:27 | **Release** run [40266921558](https://github.com/martineh4/healthqueue-platform/actions/runs/40266921558) starts (push to `main` touching `app/`) |
| 04:04:04 | `build-sign-attest` done: Trivy gate, SBOM, push, cosign keyless signature, provenance and SBOM attestations, all verified; evidence written to WORM storage |
| 04:04:12 | `open-deploy-pr` opens **PR #16** "Deploy healthqueue-api 54e272af8c22 to prod", author `app/github-actions`, label `deploy` |
| | PR #16's `pull_request` CI runs held as *action required* (see section 3) |
| | Maintainer clicks **Approve workflows to run**; all required checks pass; merge state `CLEAN` |
| 04:44:37 | PR #16 merged by the maintainer (`ce93032`) |
| 04:46:59 | The new pod is created by Argo CD in the kind cluster (resumed Codespace; sync started by **Refresh**) |

Running in the cluster afterwards:

```
healthqueue-api-7f98dc7d8b-255sb   crhealthqueueora3w.azurecr.io/healthqueue-api@sha256:afc9ef491e218c2701031aad1c967373e87e68ffad74284ec77288936f29a977
GET /version -> {"version":"0.1.0","commit":"54e272af8c2208b5ed7917822e82e132a2d159d8"}
```

The deployed pod reports the exact commit that the deploy PR names. From refresh to the new pod
being Ready took 27 s.

## 2. The deploy pull request (PR #16)

**Diff:** exactly two lines in `deploy/overlays/prod/kustomization.yaml`:

```diff
-    # Release evidence: release-evidence/healthqueue-api/b0a6df1cde36b9c96ee11dbe8a5f39492d75c4fc/
-    digest: sha256:469946516b8149d0714f1b68bab168601ad4ffd2cb20d29d6162ed516dfe59f5
+    # Release evidence: release-evidence/healthqueue-api/54e272af8c2208b5ed7917822e82e132a2d159d8/
+    digest: sha256:afc9ef491e218c2701031aad1c967373e87e68ffad74284ec77288936f29a977
```

**Body, generated:**

- **Built from:** `54e272af8c22`, with a compare link to the running release `b0a6df1`.
- **Image and replaced digest.**
- **Release run link.**
- **Signature identity:** `release.yml@refs/heads/main`.
- **Attestation links:** SLSA provenance 59770991, SBOM 59771008.
- **Vulnerabilities:** `{"fixable":{},"unfixed":{"HIGH":44,"LOW":61,"MEDIUM":58,"UNKNOWN":1}}`.
  The gate blocks fixable HIGH/CRITICAL; there were none.
- **WORM evidence path:** `release-evidence/healthqueue-api/54e272af…/run-40266921558-1/`.
- **Rollback instructions** and **independent `cosign verify` and `gh attestation verify`
  commands.**
- **Hidden marker for the DORA tooling:**

  ```
  <!-- healthqueue-release {"commit":"54e272af…","digest":"sha256:afc9ef49…","release_run":"…/runs/40266921558"} -->
  ```

**Least privilege:** `open-deploy-pr` ran outside the `release` environment, with no Azure
login or signing identity. It took 12 s.

## 3. Finding: how bot pull requests get their required checks

| Attempt | Result |
|---|---|
| As designed in #15: the bot dispatches `ci.yml` and `infra.yml` on its branch (`workflow_dispatch`) | The runs passed and their check suites were linked to PR #16's head commit. But the PR's check rollup listed only `Trivy` and stayed **BLOCKED**. Dispatching again changed nothing: GitHub does not count `workflow_dispatch` results toward a PR's required checks. |
| GitHub's own behaviour | The PR's `pull_request` runs (CI, Infra) were created but held as **action_required** with zero jobs |
| Maintainer clicked **Approve workflows to run** | All required checks ran and passed. Merge state **BLOCKED → CLEAN** |

PR #17 removed the dispatch step and `actions: write`. The deploy PR body now starts with
the procedure (approve workflows → checks → merge), and ADR-0007 records the approach that
failed. The maintainer chose the approval click over registering a GitHub App, which ADR-0007
keeps as the production path.

Repository setting enabled by the maintainer for this phase: **Allow GitHub Actions to create
and approve pull requests** (`can_approve_pull_request_reviews: true`). Workflow token
default permissions stay **read**.

## 4. Demo-day rehearsal (resumed Codespace)

Every step of the [demo-day guide](../demo-day.md) was run against the phase 7 Codespace
after it had been stopped:

| Step | Result |
|---|---|
| `gh codespace ssh` on a stopped Codespace | It started automatically. The kind node container came back up on its own (Docker restart) |
| `bootstrap-cluster.sh` on the resumed cluster | Exit 0 in 31 s |
| **Gap found** | The bootstrap reported Synced/Healthy from Argo CD's last comparison while the 76-minute-old pod still ran the previous digest. Fixed in this PR: step 5 forces a hard refresh, waits until `status.sync.revision` equals `origin/main`, then waits for the rollout. The same commands, run by hand, gave the 27 s rollout in section 1. |
| Pull secret piped from **Windows PowerShell** | `expires 2026-11-25T04:48:13Z (29 days left)` (`create-pull-secret.sh --stdin` also strips a UTF-8 BOM) |
| Argo CD UI | `kubectl port-forward` in the Codespace plus `gh codespace ports forward 8080:8080` on the laptop: `https://localhost:8080` returned 200, `<title>Argo CD</title>`, `/api/version` = `v3.5.4`. `argocd admin initial-password` returned the password (not displayed) |
| Self-heal on camera | `kubectl scale --replicas=0` while watching: `1/1 → 0/0 → 0/1 → 1/1` within seconds; Argo CD back to Synced/Healthy |
| Version bump commands (PowerShell, scratch copies) | Exactly two lines changed (`0.1.0 → 0.2.0`), no BOM written |

The Codespace was stopped after the rehearsal.

## 5. Not yet demonstrated

- **The bootstrap's new step 5, run as a script:** its commands were run by hand above, and
  the script itself runs again at the next Codespace start.
- **Rollback by reverting a deploy PR:** included in the demo-day guide as optional scene 5.
- **A newer release replacing an unmerged deploy PR:** the update branch of
  `open-deploy-pr.sh`. Expected the next time two releases happen before a merge.
