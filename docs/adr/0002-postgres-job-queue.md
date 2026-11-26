# ADR-0002: Postgres-backed job queue for ingestion

- **Status:** Accepted
- **Date:** 2026-11-26

## Context

Ingestion (parse, chunk, embed, index, activate) takes seconds to minutes per file and must
survive worker restarts without losing or duplicating work (PRD FR-04, NFR-05). The deployment
must stay within free tiers and a ~5 GB local footprint, and the cloud API and worker share one
Hugging Face Space.

## Decision

Store jobs in a Postgres `jobs` table. Workers claim the next ready job with
`SELECT … FOR UPDATE SKIP LOCKED`, hold a 60-second lease renewed by heartbeats, and any job whose
lease expires is claimed again. Each claim counts as an attempt (max 5); transient failures back
off exponentially up to 60 seconds, content errors fail immediately. Jobs carry an idempotency
key, and the indexing job clears a version's previous chunks, tables and vectors before writing,
so a re-run produces exactly one copy.

## Alternatives considered

- **Redis + RQ/Celery/arq:** mature, but another service to run locally and in the cloud (no
  durable free Redis without a card), plus a second source of truth to reconcile with Postgres.
- **In-process background tasks:** simplest, but work is lost on restart, which fails FR-04.

## Consequences

- One fewer service; jobs, documents and audit rows commit in the same database transaction.
- Throughput is bounded by Postgres row locking — ample for this workload, not for thousands of
  jobs per second.
- Crash recovery is observable and testable (`test_rerun_after_crash_leaves_no_duplicates`).
