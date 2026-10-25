# Evidence: Phase 5, signed and attested release pipeline

Captured 2026-10-25. Design: [supply chain and SLSA](../supply-chain-slsa.md),
[ADR-0003](../adr/0003-github-actions-workload-identity.md).

## 1. Release runs

| Run | Commit | Result |
|---|---|---|
| 40171216190 | `806916f` | Image built, scanned, pushed, signed, attested and **verified**. The step that writes `release.json` then failed: a jq bug (`group_by` key must be `.[0]`). No evidence was uploaded. Fixed in the next commit. |
| 40171484857 | `2cfc938` | **Success**, all steps. |

Released image:

```
crhealthqueueora3w.azurecr.io/healthqueue-api@sha256:af94a79e821fd8f5ee26c6c4089ae197aff94627c69ad0b983569ed2d3e9771c
```

## 2. In-pipeline verification (fails the release if any check fails)

- `cosign verify` with `--certificate-identity .../release.yml@refs/heads/main` and the GitHub
  OIDC issuer
- `gh attestation verify` with `--predicate-type https://slsa.dev/provenance/v1` and
  `--signer-workflow .../release.yml`
- `gh attestation verify` with `--predicate-type https://spdx.dev/Document/v2.3`

## 3. Independent verification from a workstation (not the CI runner)

```
$ gh attestation verify oci://$REF --repo martineh4/healthqueue-platform \
    --signer-workflow martineh4/healthqueue-platform/.github/workflows/release.yml \
    --predicate-type https://slsa.dev/provenance/v1
exit=0

$ gh attestation verify oci://$REF --repo martineh4/healthqueue-platform \
    --predicate-type https://spdx.dev/Document/v2.3
exit=0
```

Contents of the verified provenance:

```
subject:    crhealthqueueora3w.azurecr.io/healthqueue-api  sha256:af94a79e…9771c
builder:    https://github.com/martineh4/healthqueue-platform/.github/workflows/release.yml@refs/heads/main
workflow:   .github/workflows/release.yml  refs/heads/main
signer SAN: https://github.com/martineh4/healthqueue-platform/.github/workflows/release.yml@refs/heads/main
timestamps: Tlog (Rekor transparency log)
```

**Negative check.** Verifying a digest that was never pushed (`sha256:000…`) fails with
`MANIFEST_UNKNOWN`.

**Registry referrers.** The image digest has three Sigstore bundles attached as OCI referrers:
the cosign signature, the provenance and the SBOM attestation.

```
$ az acr manifest list-referrers -r crhealthqueueora3w -n healthqueue-api@sha256:af94a79e…
3  application/vnd.dev.sigstore.bundle.v0.3+json
```

## 4. Evidence in WORM storage

`release-evidence/healthqueue-api/2cfc9384cd8fd76707467a8212948a09308329d9/run-40171484857-1/`:

| File | Bytes |
|---|---|
| `release.json` | 1,104 |
| `sbom.spdx.json` | 2,342,999 |
| `trivy-image.json` | 840,489 |
| `provenance.sigstore.json` | 11,257 |
| `sbom-attestation.sigstore.json` | 3,134,134 |
| `cosign-verify.json` | 998 |
| `provenance-verify.json` | 14,248 |
| `sbom-verify.json` | 5,480,579 |

`release.json` from that run (excerpt):

```json
{
  "schema": "healthqueue.release/v1",
  "reference": "crhealthqueueora3w.azurecr.io/healthqueue-api@sha256:af94a79e…9771c",
  "commit": "2cfc9384cd8fd76707467a8212948a09308329d9",
  "signature": { "tool": "cosign keyless", "identity": "https://github.com/martineh4/healthqueue-platform/.github/workflows/release.yml@refs/heads/main" },
  "attestations": {
    "slsa_provenance": "https://github.com/martineh4/healthqueue-platform/attestations/59562251",
    "sbom": "https://github.com/martineh4/healthqueue-platform/attestations/59562256"
  },
  "sbom": { "format": "SPDX-2.3", "packages": 105 },
  "vulnerabilities": { "HIGH": 44, "LOW": 61, "MEDIUM": 58, "UNKNOWN": 1 }
}
```

State admins read evidence through a `Storage Blob Data Reader` grant on
`rg-healthqueue-prod`, added in the bootstrap. The CI apply identity cannot grant roles to
users (ADR-0003).

## 5. Vulnerability findings, explained

The release passed the gate: no **fixable** HIGH or CRITICAL findings. The 164 findings in the
report break down as follows:

| Severity | Fixable | Unfixed | Class |
|---|---|---|---|
| HIGH | 0 | 44 | OS packages (Debian 13.7) |
| MEDIUM | 0 | 58 | OS packages |
| LOW | 0 | 61 | OS packages |
| UNKNOWN | 0 | 1 | OS packages |

- **Python dependencies:** zero findings.
- **HIGH findings:** mostly 4 util-linux CVEs repeated across about 11 packages (`mount`,
  `login`, `libblkid1`, …). Trivy status: 43 `affected`, 1 `fix_deferred`.

Because a single total reads as alarming, `release.json` now records `vulnerabilities.fixable`
and `vulnerabilities.unfixed` separately. The residual risk is in the gaps table of the
supply-chain doc.

## 6. Not yet demonstrated

- **WORM rejection.** A negative test that overwriting or deleting evidence is refused has not
  been run. The policy is in place (`immutabilityPeriodSinceCreationInDays: 7`, `Unlocked`;
  see phase 4 evidence).
- **Deploy-time signature enforcement.** Phase 9.
