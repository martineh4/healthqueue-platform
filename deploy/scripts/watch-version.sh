#!/usr/bin/env bash
# Print what the cluster is serving every 2 seconds: the app version and the Git commit
# the image was built from (/version). Used to show a rollout live (docs/demo-day.md).
# Ctrl+C to stop.
#
# Asks the pod directly with `kubectl exec`, so it keeps working while pods are replaced;
# a port-forward would break when its pod goes away.
set -uo pipefail

NAMESPACE=${NAMESPACE:-healthqueue}
URL=http://localhost:8000/version

while true; do
  printf '%s  ' "$(date +%T)"
  kubectl -n "$NAMESPACE" exec deploy/healthqueue-api -- \
    python -c "import urllib.request; print(urllib.request.urlopen('$URL', timeout=2).read().decode())" \
    2>/dev/null || echo "(no ready pod)"
  sleep 2
done
