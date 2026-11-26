# ADR-0003: Store original files in Postgres

- **Status:** Accepted
- **Date:** 2026-11-26

## Context

Originals must be kept for "Open original", replacements, re-indexing after a profile change and
the deletion lifecycle (PRD FR-02, FR-07, NFR-07). The cloud API runs on a Hugging Face Space whose
disk is wiped on restart, and the project must stay on free tiers without a payment card.

## Decision

Keep original files and extracted Parquet tables in a `stored_files` table (bytea, deferred
loading) in the same Postgres database — local Docker or Neon in the cloud. Files are capped at
10 MB. Downloads require a session plus a short-lived HMAC link bound to file, workspace and user.

## Alternatives considered

- **S3-compatible object storage (R2, B2, S3):** the scalable choice, but the free tiers that fit
  require a payment card or add another account, and local development would need MinIO.
- **Local filesystem:** fine for Docker, but files would vanish from the cloud Space on restart.
- **Hugging Face dataset repository:** free, but git history keeps deleted files unless squashed,
  which conflicts with the deletion requirement.

## Consequences

- One code path locally and in the cloud; deletes are real deletes inside a transaction.
- Database size grows with uploads; Neon's free 0.5 GB is enough for the demo corpora (~15 MB)
  with room for reviewer uploads, and usage is visible in the operator view (P5).
- A production deployment with large volumes would move blobs to object storage behind the same
  `storage.service` interface.
