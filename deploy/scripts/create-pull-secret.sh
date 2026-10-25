#!/usr/bin/env bash
# Create or rotate the `acr-pull` imagePullSecret for the kind cluster (ADR-0004).
#
# The ACR token `kind-pull` (managed in infra/envs/prod) can only read the healthqueue-api
# repository. This script asks ACR for a fresh password with an expiry and pipes it straight
# into the cluster: it is never printed, written to disk, committed, or stored in OpenTofu
# state. Regenerating password1 invalidates the previous password1, so running this again
# is also how you rotate.
#
# Usage:
#   deploy/scripts/create-pull-secret.sh            # create/rotate, 30-day expiry
#   DAYS=7 deploy/scripts/create-pull-secret.sh     # shorter expiry (1-90)
#   deploy/scripts/create-pull-secret.sh status     # show expiry of the current secret
#
#   # Mint on a trusted workstation, install in a Codespace that has no Azure login:
#   az acr token credential generate -r crhealthqueueora3w -n kind-pull --password1 \
#       --expiration-in-days 30 --query "passwords[?name=='password1'] | [0].[value, expiry]" -o tsv \
#     | gh codespace ssh -c <codespace> -- \
#       'cd /workspaces/healthqueue-platform && deploy/scripts/create-pull-secret.sh --stdin'
#
# Needs: kubectl pointing at the target cluster, and either az (logged in with rights to
# generate token credentials, e.g. Contributor on the registry) or --stdin.
set -euo pipefail
set +x # never trace: the password passes through variables below

REGISTRY=${REGISTRY:-crhealthqueueora3w}
TOKEN_NAME=${TOKEN_NAME:-kind-pull}
NAMESPACE=${NAMESPACE:-healthqueue}
DAYS=${DAYS:-30}
SECRET=acr-pull
SERVER="$REGISTRY.azurecr.io"
EXPIRY_ANNOTATION=healthqueue.io/credential-expires-at

die() { echo "error: $*" >&2; exit 1; }

status() {
  local expiry
  expiry=$(kubectl get secret "$SECRET" -n "$NAMESPACE" \
    -o jsonpath="{.metadata.annotations.healthqueue\.io/credential-expires-at}" 2>/dev/null) \
    || die "secret $NAMESPACE/$SECRET not found; run without arguments to create it"
  local days_left=$(( ($(date -u -d "$expiry" +%s) - $(date -u +%s)) / 86400 ))
  echo "$NAMESPACE/$SECRET: token $TOKEN_NAME, expires $expiry ($days_left days left)"
  (( days_left >= 7 )) || echo "warning: rotate soon: deploy/scripts/create-pull-secret.sh" >&2
}

if [[ "${1:-}" == "status" ]]; then
  status
  exit 0
fi

for cmd in kubectl base64; do
  command -v "$cmd" >/dev/null || die "$cmd not found"
done

if [[ "${1:-}" == "--stdin" ]]; then
  # Two lines on stdin: password, then expiry (the az query in the usage above).
  { read -r password; read -r expiry; } < <(tr -d '\r')
else
  [[ "$DAYS" =~ ^[0-9]+$ ]] && (( DAYS >= 1 && DAYS <= 90 )) || die "DAYS must be 1-90"
  command -v az >/dev/null || die "az not found (or pipe a password in with --stdin)"
  echo "Generating a ${DAYS}-day password for ACR token $TOKEN_NAME (pull-only, healthqueue-api)..."
  # az prints each element of the [value, expiry] list on its own line with -o tsv.
  { read -r password; read -r expiry; } < <(az acr token credential generate \
    --registry "$REGISTRY" --name "$TOKEN_NAME" --password1 --expiration-in-days "$DAYS" \
    --query "passwords[?name=='password1'] | [0].[value, expiry]" -o tsv | tr -d '\r')
fi
[[ -n "${password:-}" && -n "${expiry:-}" ]] || die "no password/expiry received"
date -u -d "$expiry" >/dev/null 2>&1 \
  || die "expiry is not a timestamp; refusing (stdin order is password, then expiry)"

kubectl get namespace "$NAMESPACE" >/dev/null 2>&1 \
  || kubectl create namespace "$NAMESPACE" >/dev/null # Argo CD adopts it and adds PSA labels

auth=$(printf '%s:%s' "$TOKEN_NAME" "$password" | base64 -w0)
unset password

# The dockerconfigjson travels over stdin only. Server-side apply, because client-side
# `kubectl apply` would copy the whole secret into a last-applied-configuration annotation.
printf '{"auths":{"%s":{"auth":"%s"}}}' "$SERVER" "$auth" \
  | kubectl create secret generic "$SECRET" -n "$NAMESPACE" \
      --type=kubernetes.io/dockerconfigjson --from-file=.dockerconfigjson=/dev/stdin \
      --dry-run=client -o yaml \
  | kubectl apply --server-side --force-conflicts --field-manager=create-pull-secret -f - >/dev/null
unset auth

kubectl annotate secret "$SECRET" -n "$NAMESPACE" --overwrite \
  "$EXPIRY_ANNOTATION=$expiry" \
  "healthqueue.io/acr-token=$TOKEN_NAME" >/dev/null
kubectl label secret "$SECRET" -n "$NAMESPACE" --overwrite \
  app.kubernetes.io/managed-by=create-pull-secret.sh >/dev/null

status
