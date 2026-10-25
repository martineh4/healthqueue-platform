#!/usr/bin/env bash
# Installs the platform CLIs for the Codespace.
#
# Every binary is pinned to a version AND to a SHA-256 recorded here, copied from the
# project's published checksums when the version was chosen. A release asset that is
# replaced after the fact (the March 2026 Trivy incident, docs/supply-chain-slsa.md) fails
# the check instead of being installed. To bump a tool, update both lines together.
set -euo pipefail

BIN=/usr/local/bin
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

# name | version | url | sha256 | archive member ("" = plain binary)
TOOLS=(
  "kind|v0.33.0|https://github.com/kubernetes-sigs/kind/releases/download/v0.33.0/kind-linux-amd64|aee6151561422756b764a4ae28e7f44cda5af5a9eead3cc9985112b1de8d8e0d|"
  "kubectl|v1.37.1|https://dl.k8s.io/release/v1.37.1/bin/linux/amd64/kubectl|65691ff77eb6fa44c908b77a1082c9f092c3b9733b5cefabec0d1104890e21a8|"
  "argocd|v3.5.4|https://github.com/argoproj/argo-cd/releases/download/v3.5.4/argocd-linux-amd64|9cd8cb9f8f785357af441a9544cc1c63a2b8d9bad45ebe88503ab8e315c64ae3|"
  "cosign|v3.1.3|https://github.com/sigstore/cosign/releases/download/v3.1.3/cosign-linux-amd64|4629c757b7618056f8ddd7e2625ae9fdd94c0372a65049520bc7d9df9efc7f71|"
  "tofu|1.13.1|https://github.com/opentofu/opentofu/releases/download/v1.13.1/tofu_1.13.1_linux_amd64.tar.gz|378ada19d4bc70c43732004e8159be771b23b9a5afdf059e5f8a2b3fa2c70a69|tofu"
  "trivy|0.75.0|https://github.com/aquasecurity/trivy/releases/download/v0.75.0/trivy_0.75.0_Linux-64bit.tar.gz|c6e65abddb348e25f10549df887045629cf28cc72453cd1c63acb717316b3f3f|trivy"
  "syft|v1.54.1|https://github.com/anchore/syft/releases/download/v1.54.1/syft_1.54.1_linux_amd64.tar.gz|c069905b391cc4c20a5ba65ad5c10be2a7ba074f8ea6ad203e24d14e303dad47|syft"
)

for entry in "${TOOLS[@]}"; do
  IFS='|' read -r name version url sha member <<<"$entry"
  file="$TMP/$name.download"
  curl -fsSLo "$file" "$url"
  echo "$sha  $file" | sha256sum --check --strict --quiet \
    || { echo "checksum mismatch for $name $version; refusing to install" >&2; exit 1; }
  if [[ -n "$member" ]]; then
    tar -xzf "$file" -C "$TMP" "$member"
    file="$TMP/$member"
  fi
  sudo install -m 0755 "$file" "$BIN/$name"
  printf '  %-8s %-8s verified\n' "$name" "$version"
done

# Python: hash-locked runtime dependencies, then the app in editable mode with dev tools.
python -m pip install --upgrade pip
pip install --require-hashes -r app/requirements.lock
pip install -e "app[dev]"

echo "Tooling:"
for t in kind kubectl argocd tofu cosign trivy syft az gh docker; do
  printf '  %-8s %s\n' "$t" "$(command -v "$t" >/dev/null && echo ok || echo MISSING)"
done
