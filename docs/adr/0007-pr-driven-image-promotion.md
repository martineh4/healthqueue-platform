# ADR-0007: Pull-request-driven image promotion

- **Status:** Accepted
- **Date:** 2026-10-26
- **Deciders:** Platform engineering; informed: CTO
- **Related:** [ADR-0006](0006-gitops-with-argo-cd.md), [supply chain and SLSA](../supply-chain-slsa.md),
  [`release.yml`](../../.github/workflows/release.yml), [`open-deploy-pr.sh`](../../.github/scripts/open-deploy-pr.sh)

## Context

`release.yml` produces a signed, attested, verified image for every merge that touches the app.
Production runs whatever digest `deploy/overlays/prod` pins, and Argo CD syncs that from
`main` (ADR-0006). Something has to move the new digest into that file.

Requirements:

1. **Every production change is a reviewed pull request,** with the same required checks as
   any other change. No path writes to `main` directly.
2. **Only verified images are proposed.** The proposal happens after the signature and both
   attestations have been verified, never before.
3. **The reviewer sees what they are approving:** the source commit, the change since the
   running release, the digest, the vulnerability summary and the evidence location.
4. **Rollback is a revert.**
5. **Deployments are measurable** (DORA, phase 11): the commit, the merge time and the
   release are recoverable from the pull request.

## Decision

A job named `open-deploy-pr` runs at the end of `release.yml`, after the signing and
verification job succeeds.

- **Least privilege:** the job is outside the `release` environment, so it has no Azure,
  registry or signing access. Its token can push branches (`main` is protected), open pull
  requests and dispatch workflows.
- **One branch, one open pull request:** it rewrites the digest and the evidence comment in
  the prod overlay on the fixed branch `deploy/prod-healthqueue-api`, starting from the current
  `main`. If a deploy pull request is already open, a newer release replaces it. Nobody can
  merge a stale release after a newer one exists. If `main` already deploys the digest, it does
  nothing.
- **Reviewer-facing body:** the pull request describes the commit, a compare link against the
  running release, the digest it replaces, signature and attestation links, vulnerability
  counts, the WORM evidence path, rollback instructions and `cosign verify` and
  `gh attestation verify` commands. A hidden `healthqueue-release` JSON marker carries the
  commit and digest for the DORA tooling.
- **Merge = deploy.** Argo CD polls `main` (up to 3 minutes; **Refresh** in the UI is
  immediate). **Rollback** is reverting the merge commit, which is itself a pull request.
- **Not auto-merged.** With one maintainer, the merge button is the deliberate human
  approval of a production change.

### Approving the pull request's CI runs

A pull request opened with the job's `GITHUB_TOKEN` gets its `pull_request` workflow runs,
but GitHub holds them as **"action required"** until a maintainer clicks **Approve workflows
to run** on the pull request. Then the required checks run as on any other pull request.
Every push to the bot branch (a newer release) needs the approval again.

The deploy procedure is therefore: **approve workflows → checks pass → merge.** The approval
is also a deliberate human decision before bot-authored changes run in CI.

*What did not work (2026-10-26):* dispatching `ci.yml` and `infra.yml` on the bot branch with
`workflow_dispatch`, the one event `GITHUB_TOKEN` may trigger. The runs passed on the pull
request's head commit, but GitHub does not count `workflow_dispatch` results toward a pull
request's required checks, and the pull request stayed blocked. That approach was removed.
`infra.yml`'s drift job still runs on manual dispatch only from `main`, because `prod` rejects
other branches.

Opening a pull request with `GITHUB_TOKEN` needs the repository setting **"Allow GitHub
Actions to create and approve pull requests"**. That setting also lets workflows approve
pull requests. It has no effect today, because branch protection requires zero approvals
(one maintainer).

## Consequences

**Positive**

- A release becomes a production change only through a pull request with green checks, and
  every deployment has a reviewable record.
- The supply-chain evidence travels with the decision: a reviewer can verify the image
  independently before merging.
- The bump is small and mechanical (two lines in one file), so the diff is easy to review.
- Lead time (commit → merge of the deploy pull request) and deployment frequency
  (merged deploy pull requests) come straight from the GitHub API.

**Negative / accepted risks**

- **The bot's identity is `github-actions[bot]`,** shared by every workflow in the repository.
  A dedicated GitHub App would give the bot its own identity and its own audit trail.
- **The "create and approve" setting must not stay on once approvals are required.** If a
  second maintainer joins and branch protection requires a review, a workflow could approve
  its own pull request. At that point, switch to a GitHub App token (below) and turn the
  setting off.
- **One extra click per deploy:** approving the held CI runs. A GitHub App token removes it.
- **Deploy pull requests can go stale.** Strict branch protection requires the branch to be
  up to date with `main`. If `main` moves, use **Update branch** on the pull request, or let
  the next release rebuild the branch from `main`.

## Alternatives considered

| Option | Why rejected (for now) |
|---|---|
| GitHub App token (`actions/create-github-app-token`) | **The production choice.** It gives the bot its own identity, pull requests whose CI runs without an approval click, and no need for the "create and approve" setting. It needs an App registration and a private key stored as a secret. Deferred by the maintainer (one extra click per deploy is acceptable for now). Adopt it when a second maintainer or required reviews arrive. |
| `workflow_dispatch` the required checks on the bot branch | Tried. GitHub does not count dispatched runs toward the pull request's required checks. |
| Personal access token | Ties production changes to one person's account and holds a long-lived secret. Fine-grained tokens still expire and need manual rotation. |
| Argo CD Image Updater | Changes production without a pull request, failing requirement 1 (also rejected in ADR-0006). |
| Commit the bump directly to `main` | Bypasses branch protection and review entirely. |
| Auto-merge when checks pass | Removes the human decision, which is the only approval a one-person team has. Reasonable later for a staging overlay. |

## Revisit when

- A second maintainer joins or reviews become required: switch to a GitHub App and disable
  "Allow GitHub Actions to create and approve pull requests".
- A staging environment exists: promote to staging automatically, and to prod by pull request
  once staging has been healthy.
- Phase 9 (Kyverno) enforces the signature at admission, so an unsigned digest is rejected
  by the cluster even if it were merged.
