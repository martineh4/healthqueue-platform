#!/usr/bin/env bash
# Propose a verified release for production as a pull request (ADR-0007).
#
# Called by release.yml after the image is signed, attested and verified. Rewrites the
# image digest in the prod overlay on a fixed branch, then opens the pull request, or
# updates it if one is already open (a newer release replaces an unmerged older one).
# Merging the pull request is the deployment: Argo CD syncs main.
#
# GitHub holds the pull request's CI runs for approval because GITHUB_TOKEN opened it: a
# maintainer clicks "Approve workflows to run", the required checks run, then the
# maintainer merges (ADR-0007).
#
# Env: IMAGE DIGEST COMMIT RUN_URL VULNS PROVENANCE_URL SBOM_URL EVIDENCE_PATH
#      SIGNER_IDENTITY OIDC_ISSUER GITHUB_REPOSITORY GH_TOKEN
set -euo pipefail

OVERLAY=deploy/overlays/prod/kustomization.yaml
BRANCH=deploy/prod-healthqueue-api

die() { echo "error: $*" >&2; exit 1; }

[[ "$DIGEST" =~ ^sha256:[0-9a-f]{64}$ ]] || die "DIGEST is not a sha256 digest: $DIGEST"
[[ "$COMMIT" =~ ^[0-9a-f]{40}$ ]] || die "COMMIT is not a full commit SHA: $COMMIT"

git fetch --quiet --no-tags origin main
git switch --quiet --force-create "$BRANCH" origin/main

digest_re='^ *digest: sha256:[0-9a-f]{64} *$'
evidence_re='^ *# Release evidence: release-evidence/healthqueue-api/[0-9a-f]{40}/ *$'
[[ $(grep -cE "$digest_re" "$OVERLAY") == 1 ]] || die "expected exactly one digest line in $OVERLAY"
[[ $(grep -cE "$evidence_re" "$OVERLAY") == 1 ]] || die "expected exactly one evidence comment in $OVERLAY"

current=$(grep -oE 'sha256:[0-9a-f]{64}' "$OVERLAY")
previous_commit=$(grep -E "$evidence_re" "$OVERLAY" | grep -oE '[0-9a-f]{40}')
if [[ "$current" == "$DIGEST" ]]; then
  echo "$DIGEST is already what main deploys; nothing to propose"
  exit 0
fi

sed -i -E \
  -e "s#^( *digest: )sha256:[0-9a-f]{64}#\1$DIGEST#" \
  -e "s#^( *\# Release evidence: release-evidence/healthqueue-api/)[0-9a-f]{40}/#\1$COMMIT/#" \
  "$OVERLAY"
grep -qE "^ *digest: $DIGEST *$" "$OVERLAY" || die "digest rewrite failed"
git diff --stat

short=${COMMIT::12}
git -c user.name='github-actions[bot]' \
    -c user.email='41898282+github-actions[bot]@users.noreply.github.com' \
    commit --quiet --all \
    --message "Deploy healthqueue-api $short to prod" \
    --message "Image: $IMAGE@$DIGEST
Release run: $RUN_URL"
git push --quiet --force origin "HEAD:refs/heads/$BRANCH"

server=${GITHUB_SERVER_URL:-https://github.com}
body=$(mktemp)
cat > "$body" <<EOF
Deploys a verified release of \`healthqueue-api\` to **prod**. Merging this pull request is the
deployment: Argo CD syncs \`main\` within 3 minutes (or press **Refresh** in the UI).

**To deploy:** click **Approve workflows to run** below (bot pull requests wait for a
maintainer before CI runs), wait for the required checks, then merge.

| | |
|---|---|
| Built from | [\`$short\`]($server/$GITHUB_REPOSITORY/commit/$COMMIT) ([changes since the running release]($server/$GITHUB_REPOSITORY/compare/$previous_commit...$COMMIT)) |
| Image | \`$IMAGE@$DIGEST\` |
| Replaces | \`$current\` |
| Release run | $RUN_URL |
| Signature | cosign keyless, verified for \`$SIGNER_IDENTITY\` |
| Attestations | [SLSA provenance]($PROVENANCE_URL), [SBOM]($SBOM_URL), verified with \`gh attestation verify\` |
| Vulnerabilities | \`$VULNS\` (the release gate blocks fixable HIGH/CRITICAL) |
| Evidence (WORM) | \`$EVIDENCE_PATH\` |

**Rollback:** revert this pull request's merge commit. Argo CD then syncs the previous digest.

Verify independently:

\`\`\`bash
cosign verify $IMAGE@$DIGEST \\
  --certificate-identity $SIGNER_IDENTITY \\
  --certificate-oidc-issuer $OIDC_ISSUER
gh attestation verify oci://$IMAGE@$DIGEST --repo $GITHUB_REPOSITORY
\`\`\`

<!-- healthqueue-release {"commit":"$COMMIT","digest":"$DIGEST","release_run":"$RUN_URL"} -->
EOF

title="Deploy healthqueue-api $short to prod"
number=$(gh pr list --head "$BRANCH" --base main --state open --json number --jq '.[0].number // empty')
if [[ -n "$number" ]]; then
  gh pr edit "$number" --title "$title" --body-file "$body" >/dev/null
  echo "updated pull request #$number"
else
  gh pr create --base main --head "$BRANCH" --title "$title" --body-file "$body" --label deploy
fi
echo "CI on $BRANCH is waiting for a maintainer to approve it on the pull request"
