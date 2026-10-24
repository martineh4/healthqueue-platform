#!/usr/bin/env bash
# Installs the platform CLIs not covered by devcontainer features.
# Versions are pinned for reproducibility; bump them deliberately.
set -euo pipefail

KIND_VERSION="v0.27.0"
ARGOCD_VERSION="v3.0.0"
TOFU_VERSION="1.13.0"
COSIGN_VERSION="v2.5.0"
TRIVY_VERSION="0.61.0"
SYFT_VERSION="v1.20.0"

BIN=/usr/local/bin
ARCH=amd64

sudo curl -fsSLo "$BIN/kind" "https://kind.sigs.k8s.io/dl/${KIND_VERSION}/kind-linux-${ARCH}"
sudo curl -fsSLo "$BIN/argocd" "https://github.com/argoproj/argo-cd/releases/download/${ARGOCD_VERSION}/argocd-linux-${ARCH}"
sudo curl -fsSLo "$BIN/cosign" "https://github.com/sigstore/cosign/releases/download/${COSIGN_VERSION}/cosign-linux-${ARCH}"
sudo chmod +x "$BIN/kind" "$BIN/argocd" "$BIN/cosign"

curl -fsSL "https://github.com/opentofu/opentofu/releases/download/v${TOFU_VERSION}/tofu_${TOFU_VERSION}_linux_${ARCH}.tar.gz" \
  | sudo tar -xz -C "$BIN" tofu
curl -fsSL "https://github.com/aquasecurity/trivy/releases/download/v${TRIVY_VERSION}/trivy_${TRIVY_VERSION}_Linux-64bit.tar.gz" \
  | sudo tar -xz -C "$BIN" trivy
curl -fsSL "https://github.com/anchore/syft/releases/download/${SYFT_VERSION}/syft_${SYFT_VERSION#v}_linux_${ARCH}.tar.gz" \
  | sudo tar -xz -C "$BIN" syft

python -m pip install --upgrade pip
pip install -e "app[dev]"

echo "Tooling installed:"
for t in kind argocd tofu cosign trivy syft kubectl helm az gh; do
  printf '  %-7s %s\n' "$t" "$(command -v $t >/dev/null && echo ok || echo MISSING)"
done
