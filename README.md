# HealthQueue Platform

Reference DevOps architecture for the HealthQueue patient appointment scheduling API:
CI/CD with supply-chain security, OpenTofu on Azure, and GitOps delivery to Kubernetes via Argo CD.

> Status: work in progress. Phases 0–1 (repo skeleton, API + tests) are complete.

## Repository layout

| Path | Purpose |
|---|---|
| `app/` | FastAPI appointment API, tests, Dockerfile |
| `.github/workflows/` | CI (PR checks), release (build → scan → SBOM → sign → attest), infra |
| `infra/` | OpenTofu: state bootstrap, Azure modules, `prod` environment |
| `deploy/` | Kustomize base/overlays and Argo CD applications |
| `observability/` | SLO recording rules, burn-rate alerts, dashboards |
| `dora/` | Synthetic 90-day deployment data generator and analysis |
| `docs/` | Architecture, ADRs, runbooks, SLO, SLSA, and DORA reports |
| `.devcontainer/` | Codespace with Docker, kind, Argo CD, OpenTofu, cosign, Trivy, Syft |

## Quickstart (no Docker required)

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
