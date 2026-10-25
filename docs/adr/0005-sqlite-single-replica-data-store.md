# ADR-0005: SQLite on a single replica for the course environment; PostgreSQL for production

- **Status:** Accepted
- **Date:** 2026-10-25
- **Deciders:** Platform engineering; informed: CTO
- **Related:** [`deploy/base/deployment.yaml`](../../deploy/base/deployment.yaml),
  [`app/src/healthqueue/store.py`](../../app/src/healthqueue/store.py)

## Context

The appointment API stores appointments in SQLite (`AppointmentStore`). The store enforces
double-booking rules inside a transaction behind a process-level lock. That is correct for
**one process writing one database file**.

Kubernetes makes horizontal scaling look free. With SQLite it is not:

- Two pods cannot safely share one SQLite file over a network or shared volume. File locking is
  unreliable on most network filesystems, and the in-process lock does not span pods. Running
  two replicas would allow double-bookings, or corrupt the database.
- A `RollingUpdate` briefly runs the old and new pod together, which is exactly that situation.
- On kind, PersistentVolumes come from `local-path` storage, which is tied to one node.

The data is synthetic; no real patient information is processed (`data_classification =
internal-no-phi` on every Azure resource).

## Decision

For the course environment:

- **SQLite on a `ReadWriteOnce` PersistentVolumeClaim** (`healthqueue-data`, 1 GiB), file
  `/data/healthqueue.db`.
- **`replicas: 1` and `strategy: Recreate`.** The old pod stops before the new one starts, so
  there is never more than one writer.
- **No PodDisruptionBudget.** With one replica, a PDB of `minAvailable: 1` would block node
  drains forever, and `maxUnavailable: 1` would be meaningless.
- **No HorizontalPodAutoscaler.**

For **production**, the path is **Azure Database for PostgreSQL – Flexible Server**:

| Concern | Production design |
|---|---|
| Availability | Zone-redundant HA (standby in another zone, automatic failover) |
| Recovery | Point-in-time restore (up to 35 days), geo-redundant backups to the paired DR region (ADR-0001) |
| Access | Private access (VNet integration) only; Entra ID authentication from pods via **Workload Identity**, no database password |
| Concurrency | Double-booking prevented with an exclusion constraint (`tstzrange` overlap per provider and per patient), enforced by the database rather than application locks |
| Application | ≥ 2 replicas, `RollingUpdate`, `PodDisruptionBudget minAvailable: 1`, HPA on CPU and request rate |
| Schema changes | Versioned migrations run as a pre-sync Argo CD hook, written expand-then-contract so old and new pods can run together |

The application change is contained: `AppointmentStore` is the only class that touches the
database, and its interface (`book`, `get`, `find`, `cancel`, `booked_between`, `ping`) maps
directly onto SQL.

## Consequences

**Positive**

- The course environment needs no managed database (about $15–30/month for the smallest
  Flexible Server, more with HA) and no network setup.
- The single-writer guarantee holds by construction, not by hoping replicas never overlap.

**Negative / accepted risks**

- **Every deploy causes downtime**, typically a few seconds while the new pod starts and passes
  readiness. This counts against the availability SLO (phase 10). At a 99.5% monthly target the
  budget is about 216 minutes, so even several deploys a day use well under 1% of it. Phase 10
  measures the actual figure.
- **No high availability.** A node or pod failure means downtime until the pod is rescheduled.
  On kind's `local-path` storage, the volume is bound to one node, so the pod can only restart
  there.
- **No backups.** Deleting the PVC or the kind cluster loses the data. That is acceptable for
  synthetic data in a disposable cluster and unacceptable with real data.
- **Throughput is capped** at one pod's capacity.

## Alternatives considered

| Option | Why rejected (for now) |
|---|---|
| PostgreSQL in the cluster (StatefulSet or operator, e.g. CloudNativePG) | Realistic, but adds an operator, backups and upgrades to run inside a short-lived Codespace. Most of that effort would not carry over to the managed-service production design. |
| Azure Database for PostgreSQL from kind | kind runs outside Azure, so the database would need a public endpoint plus a credential in the cluster. That reintroduces the problems ADR-0004 avoids, and adds cost. |
| SQLite with several replicas and a shared `ReadWriteMany` volume | Unsafe: SQLite locking over network filesystems is unreliable, and the application lock is per process. |
| LiteFS / rqlite (replicated SQLite) | Interesting, but niche. It does not reflect what HealthQueue would run in production. |

## Revisit when

- Before any real patient data is processed: PostgreSQL with HA and backups is a prerequisite.
- The availability SLO is raised above what single-replica deploys allow (phase 10 error budget
  data).
- Load requires more than one pod.
