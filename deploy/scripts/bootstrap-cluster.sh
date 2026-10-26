#!/usr/bin/env bash
# Bring up the local GitOps environment in a Codespace (ADR-0006). Idempotent: re-run it
# after any step fails.
#
#   1. kind cluster `healthqueue` (node image pinned by digest)
#   2. Argo CD from deploy/argocd/install (commit- and digest-pinned)
#   3. Check the registry pull secret exists (it is never in Git; ADR-0004)
#   4. Seed the AppProjects, then apply the app-of-apps root; from then on Argo CD syncs
#      everything from main
#   5. Wait for the HealthQueue API to be Synced and Healthy
#
# Usage: deploy/scripts/bootstrap-cluster.sh
set -euo pipefail

CLUSTER=healthqueue
ROOT=$(git -C "$(dirname "$0")" rev-parse --show-toplevel)
cd "$ROOT"

step() { printf '\n==> %s\n' "$*"; }
die() { echo "error: $*" >&2; exit 1; }

for cmd in docker kind kubectl; do
  command -v "$cmd" >/dev/null || die "$cmd not found (rebuild the Codespace?)"
done

step "1/5 kind cluster '$CLUSTER'"
if kind get clusters 2>/dev/null | grep -qx "$CLUSTER"; then
  echo "exists"
  # After a Codespace stop/start the node container is stopped, and the API server's host
  # port can change when it restarts; re-export the kubeconfig either way.
  node="$CLUSTER-control-plane"
  if [[ "$(docker inspect -f '{{.State.Running}}' "$node")" != true ]]; then
    echo "node container stopped (Codespace restarted?); starting it"
    docker start "$node" >/dev/null
  fi
  kind export kubeconfig --name "$CLUSTER" >/dev/null
  for _ in $(seq 1 60); do kubectl get --raw /readyz >/dev/null 2>&1 && break; sleep 3; done
  kubectl wait --for condition=Ready node --all --timeout=180s >/dev/null
else
  kind create cluster --config deploy/kind/cluster.yaml --wait 120s
fi
kubectl config use-context "kind-$CLUSTER" >/dev/null
kubectl get nodes -o wide

step "2/5 Argo CD"
# Server-side apply: Argo CD's CRDs are too large for client-side apply's annotation.
kubectl apply --server-side --force-conflicts -k deploy/argocd/install >/dev/null
kubectl wait --for condition=established --timeout=120s \
  crd/applications.argoproj.io crd/appprojects.argoproj.io >/dev/null
for d in argocd-server argocd-repo-server argocd-redis argocd-dex-server; do
  kubectl -n argocd rollout status "deployment/$d" --timeout=300s
done
kubectl -n argocd rollout status statefulset/argocd-application-controller --timeout=300s

step "3/5 registry pull secret"
if ! kubectl -n healthqueue get secret acr-pull >/dev/null 2>&1; then
  cat >&2 <<'MSG'
The acr-pull secret is missing. Create it, then re-run this script:
  deploy/scripts/create-pull-secret.sh              # if az is logged in here
or pipe a password in from a trusted workstation (see the script's usage, --stdin).
MSG
  exit 2
fi
deploy/scripts/create-pull-secret.sh status

step "4/5 app-of-apps root"
# The root belongs to the `platform` AppProject, which is defined inside what the root syncs.
# Argo CD will not start an Application whose project does not exist yet, so seed the
# projects first; the root then adopts them from Git like everything else. Both are applied
# by hand once per cluster, and re-applying is harmless.
kubectl apply --server-side --force-conflicts -f deploy/argocd/projects/
kubectl apply -f deploy/argocd/root.yaml

step "5/5 waiting for healthqueue-api (Synced + Healthy)"
for app in root argocd healthqueue-api; do
  for _ in $(seq 1 60); do
    kubectl -n argocd get application "$app" >/dev/null 2>&1 && break
    sleep 5
  done
done
kubectl -n argocd wait application/healthqueue-api \
  --for=jsonpath='{.status.sync.status}'=Synced --timeout=600s
kubectl -n argocd wait application/healthqueue-api \
  --for=jsonpath='{.status.health.status}'=Healthy --timeout=600s

kubectl -n argocd get applications
kubectl -n healthqueue get pods,svc,pvc,networkpolicy

cat <<'MSG'

Done. Useful next commands:
  kubectl -n healthqueue port-forward svc/healthqueue-api 8000:80     # API on :8000
  kubectl -n argocd port-forward svc/argocd-server 8080:443           # Argo CD UI on :8080
  argocd admin initial-password -n argocd                             # UI login (admin)
MSG
