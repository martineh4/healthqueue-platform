# Course guide

Reference material for reviewers of the capstone: where each rubric criterion is covered, the
build phases, a documentation index, the repository layout, and how to run the API locally.
The project overview is in the [README](../README.md).

## Rubric map

Where each part of the capstone rubric (150 points, five criteria of 30) is covered, and the
evidence that shows it working.

**Required supporting documents**

| Document | File |
|---|---|
| Observability plan | [`docs/observability.md`](observability.md) |
| DORA analysis | [`docs/dora-report.md`](dora-report.md) |
| Supply chain security summary | [`docs/supply-chain-slsa.md`](supply-chain-slsa.md) |

### 1. CI/CD Pipeline with Supply Chain Security (CLO2)

| Rubric asks for | Where | Evidence |
|---|---|---|
| Build | [`release.yml`](../.github/workflows/release.yml): digest-pinned base, hash-locked dependencies ([`app/Dockerfile`](../app/Dockerfile), [`requirements.lock`](../app/requirements.lock)) | [Phase 5: release runs](evidence/phase-5-release.md#1-release-runs) |
| Test | [`ci.yml`](../.github/workflows/ci.yml) `lint-test`: ruff, pytest with an 85% coverage gate; required on every pull request | [`ci.yml`](../.github/workflows/ci.yml) required checks |
| Vulnerability scan | Trivy on the repository and the image in every pull request; release gate on fixable HIGH and CRITICAL | [Phase 5: vulnerability findings](evidence/phase-5-release.md#5-vulnerability-findings-explained) |
| SBOM | Syft SPDX SBOM, attested to the image | [Phase 5: in-pipeline verification](evidence/phase-5-release.md#2-in-pipeline-verification-fails-the-release-if-any-check-fails) |
| Signed artifacts | cosign keyless signature and SLSA provenance, verified in the pipeline and independently | [Phase 5: independent verification](evidence/phase-5-release.md#3-independent-verification-from-a-workstation-not-the-ci-runner), [WORM evidence](evidence/phase-5-release.md#4-evidence-in-worm-storage) |
| SLSA alignment documented | [Supply chain summary: SLSA assessment](supply-chain-slsa.md#slsa-assessment) (Build L2; the L3 gap and its plan), [controls by threat](supply-chain-slsa.md#controls-by-threat) | [Supply chain: gaps](supply-chain-slsa.md#gaps-and-roadmap) |

### 2. Infrastructure as Code and GitOps Deployment (CLO3)

| Rubric asks for | Where | Evidence |
|---|---|---|
| OpenTofu provisions cloud resources | [`infra/`](../infra/README.md): registry, evidence storage, CI identities on Azure | [Phase 4: merge applies](evidence/phase-4-iac-oidc.md#4-merge-apply-as-the-apply-identity) |
| Remote state | Encrypted, locked Azure state ([ADR-0002](adr/0002-opentofu-state-management.md), [how state is handled](../infra/README.md#how-state-is-handled)) | [Phase 3: ciphertext at rest](evidence/phase-3-remote-state.md#4-state-is-ciphertext-at-rest), [locking](evidence/phase-3-remote-state.md#5-locking-prevents-concurrent-runs) |
| Containerized app on Kubernetes | [`app/Dockerfile`](../app/Dockerfile), [`deploy/`](../deploy/README.md): hardened manifests under `restricted` Pod Security | [Phase 7: workload verification](evidence/phase-7-argocd.md#3-workload-verification), [phase 10: Pod Security](evidence/phase-10-observability.md#3-pod-security) |
| Deployed via Argo CD | App of apps ([ADR-0006](adr/0006-gitops-with-argo-cd.md)) | [Phase 7: GitOps controls](evidence/phase-7-argocd.md#4-gitops-controls) |
| PR-driven workflow | Infrastructure: plan on the PR, apply on merge ([infra pull requests](../infra/README.md#day-to-day-prod-pull-requests)). Application: a deploy PR per release, where merge = deploy ([ADR-0007](adr/0007-pr-driven-image-promotion.md)) | [Phase 4: plan on the PR](evidence/phase-4-iac-oidc.md#3-pull-request-4-plan-as-the-read-only-identity), [phase 8](evidence/phase-8-deploy-pr.md) |

### 3. DORA Metrics Analysis and Toil Reduction (CLO4)

| Rubric asks for | Where | Evidence |
|---|---|---|
| Synthetic 90-day DORA data | [`dora/generate.py`](../dora/generate.py) (seeded, modelling the real pipeline), [`dora/data/`](../dora/data/) | [How the data is made](dora-report.md#how-the-data-is-made) |
| Analyzed against benchmarks | [`dora/analyze.py`](../dora/analyze.py): the four metrics against the DORA 2024 elite, high, medium and low levels, with charts | [Summary](dora-report.md#summary), [robustness across 20 seeds](dora-report.md#robustness-across-seeds) |
| Toil-reduction recommendations tied to evidence | Each recommendation cites a number from the data and a projection from rerunning the same seed | [Recommendations](dora-report.md#recommendations-in-order), [toil](dora-report.md#toil) |

CI regenerates the data, report and charts on every pull request and fails if the committed
files differ.

### 4. Observability and SRE Reliability Evaluation (CLO5)

| Rubric asks for | Where | Evidence |
|---|---|---|
| SLIs/SLOs for the appointment API | [Service level objectives](observability.md#service-level-objectives): availability 99.5%, latency 99% in 300 ms, over 30 days | [Phase 10: Prometheus scrapes the API](evidence/phase-10-observability.md#4-prometheus-scrapes-the-api) |
| Error budget computed | Budget per SLO (0.5% of requests, about 3.6 hours of outage in 30 days), recording rules, [error budget policy](observability.md#error-budget-policy), burn-rate alerts with unit tests ([`observability/`](../observability/)) | [Phase 10: live budget and rules](evidence/phase-10-observability.md#9-re-check-after-pr-21-merged) |
| Metrics, logs and traces, with rationale | [Signals](observability.md#signals): metrics, JSON logs without PHI. [Gaps and production differences](observability.md#gaps-and-production-differences): log store and tracing, and why not yet ([ADR-0008](adr/0008-observability-and-slos.md)) | [Phase 10: Grafana loads the dashboard](evidence/phase-10-observability.md#6-grafana-loads-the-dashboard) |

### 5. Production-Grade Design and Technical Documentation (CLO6)

| Rubric asks for | Where |
|---|---|
| Architecture | [`docs/architecture.md`](architecture.md): system diagram, change flow, trust boundaries, course and production designs |
| Runbooks | [`docs/runbooks/`](runbooks/): API unavailable, SLO burn rate, Argo CD sync, image pull failures |
| ADRs | [Eight ADRs](adr/README.md), each with alternatives considered and when to revisit |
| README | [`README.md`](../README.md): the project as a case study |
| Decisions and trade-offs for a CTO | [Problem statement and key design decisions](../README.md#key-design-decisions); [course environment and production](architecture.md#course-environment-and-production); [supply chain summary for leadership](supply-chain-slsa.md#summary-for-leadership); the approval-click trade-off ([DORA report](dora-report.md#1-decide-when-to-trade-the-approval-click-for-speed)) |

## Phases

| Phase | Delivered | Status | Evidence |
|---|---|---|---|
| 0–1 | Repository scaffold; appointment API with tests | Done | `app/tests`, CI `lint-test` |
| 2 | PR pipeline (lint, tests with an 85% coverage gate, hadolint, Trivy); hardened image | Done | [`ci.yml`](../.github/workflows/ci.yml) |
| 3 | OpenTofu remote state, encrypted with a Key Vault key | Done | [phase 3](evidence/phase-3-remote-state.md), [ADR-0002](adr/0002-opentofu-state-management.md) |
| 4 | Infrastructure by pull request, with GitHub OIDC and least-privilege identities | Done | [phase 4](evidence/phase-4-iac-oidc.md), [ADR-0003](adr/0003-github-actions-workload-identity.md) |
| 5 | Signed, attested release pipeline with WORM evidence | Done | [phase 5](evidence/phase-5-release.md), [supply chain](supply-chain-slsa.md) |
| 6 | Hardened Kustomize manifests; pull-only registry token | Done | [phase 6](evidence/phase-6-manifests.md), [ADR-0004](adr/0004-registry-pull-authentication.md) |
| 7 | GitOps with Argo CD (app of apps) on kind | Done | [phase 7](evidence/phase-7-argocd.md), [ADR-0006](adr/0006-gitops-with-argo-cd.md) |
| 8 | A deploy pull request for every verified release | Done | [phase 8](evidence/phase-8-deploy-pr.md), [ADR-0007](adr/0007-pr-driven-image-promotion.md) |
| 9 | Signature enforcement at admission (Kyverno) | **Deferred** | [supply chain gaps](supply-chain-slsa.md#gaps-and-roadmap) |
| 10 | Monitoring stack, SLOs, burn-rate alerts, dashboard | Done, verified live | [phase 10](evidence/phase-10-observability.md), [ADR-0008](adr/0008-observability-and-slos.md) |
| 11 | DORA metrics from a seeded 90-day simulation | Done | [DORA report](dora-report.md) |
| 12 | Documentation: architecture, README, consistency pass | Done | [architecture](architecture.md) |

## Documentation

| | |
|---|---|
| Decisions | [ADR index](adr/README.md): region, state, CI identity, registry pull, data store, GitOps, promotion, observability |
| Operations | Runbooks: [API unavailable](runbooks/api-unavailable.md), [SLO burn rate](runbooks/slo-burn-rate.md), [Argo CD sync](runbooks/argocd-sync.md), [image pull failures](runbooks/image-pull-failures.md) |
| Evidence | [`docs/evidence/`](evidence/): what was run, when, and what it showed, for each phase |
| Component guides | [Infrastructure](../infra/README.md), [Kubernetes deployment](../deploy/README.md) |

## Repository layout

| Path | Purpose |
|---|---|
| `app/` | FastAPI appointment API, tests, Dockerfile |
| `.github/workflows/` | CI (PR checks), release (build → scan → SBOM → sign → attest), infra |
| `infra/` | OpenTofu: state bootstrap, Azure modules, `prod` environment |
| `deploy/` | Kustomize base/overlays and Argo CD applications |
| `observability/` | The API's scrape config, SLO recording rules, burn-rate alerts (with promtool tests) and Grafana dashboard ([docs](observability.md)) |
| `dora/` | Seeded 90-day deployment simulation, DORA metrics and charts ([report](dora-report.md)) |
| `docs/` | Architecture, ADRs, runbooks, evidence, and the observability, supply chain and DORA documents |
| `.devcontainer/` | Codespace with Docker, kind, Argo CD, OpenTofu, cosign, Trivy, Syft |

## Quickstart (no Docker required)

Use Python 3.13 to match CI and the container image (`uv venv --python 3.13` works if it is
not installed).

```bash
cd app
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
pytest                           # tests + coverage gate (85%)
uvicorn healthqueue.main:app --reload
```

Open http://localhost:8000/docs for the interactive API.

## API

| Method | Path | Description |
|---|---|---|
| `POST` | `/v1/appointments` | Book an appointment (409 on provider/patient clash) |
| `GET` | `/v1/appointments?provider_id=&patient_id=` | List appointments (one filter required) |
| `GET` | `/v1/appointments/{id}` | Fetch one appointment |
| `POST` | `/v1/appointments/{id}/cancel` | Cancel an appointment |
| `GET` | `/v1/providers/{provider_id}/availability?date=YYYY-MM-DD` | Free slots for a day |
| `GET` | `/healthz`, `/readyz`, `/metrics` | Liveness, readiness, Prometheus metrics |

Configuration is via environment variables: `HQ_DB_PATH`, `HQ_CLINIC_OPEN_HOUR`,
`HQ_CLINIC_CLOSE_HOUR`, `HQ_SLOT_MINUTES`, `HQ_LOG_LEVEL`.
