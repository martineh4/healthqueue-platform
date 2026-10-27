# HealthQueue Platform

Reference DevOps architecture for the HealthQueue patient appointment scheduling API:
CI/CD with supply-chain security, OpenTofu on Azure, and GitOps delivery to Kubernetes via Argo CD.

> Status: work in progress. Phases 0–8, 10 and 11 are complete: API and tests, PR pipeline, encrypted
> remote state, PR-driven infrastructure delivery with OIDC, a signed, attested release
> pipeline ([supply chain and SLSA](docs/supply-chain-slsa.md)), hardened Kustomize
> manifests ([deploy/](deploy/README.md)), GitOps delivery with Argo CD on kind
> ([evidence](docs/evidence/phase-7-argocd.md)), and a deploy pull request for every verified
> release ([ADR-0007](docs/adr/0007-pr-driven-image-promotion.md)), and SLOs with burn-rate
> alerts and a Grafana dashboard ([observability](docs/observability.md),
> [evidence](docs/evidence/phase-10-observability.md)), and DORA metrics from 90 days of
> synthetic deployments, with the toil to remove first ([DORA report](docs/dora-report.md)).
> Live walkthrough:
> [demo-day guide](docs/demo-day.md).

## Repository layout

| Path | Purpose |
|---|---|
| `app/` | FastAPI appointment API, tests, Dockerfile |
| `.github/workflows/` | CI (PR checks), release (build → scan → SBOM → sign → attest), infra |
| `infra/` | OpenTofu: state bootstrap, Azure modules, `prod` environment |
| `deploy/` | Kustomize base/overlays and Argo CD applications |
| `observability/` | The API's scrape config, SLO recording rules, burn-rate alerts (with promtool tests) and Grafana dashboard ([docs](docs/observability.md)) |
| `dora/` | Seeded 90-day deployment simulation, DORA metrics and charts ([report](docs/dora-report.md)) |
| `docs/` | Architecture, ADRs, runbooks, SLO, SLSA, and DORA reports |
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
