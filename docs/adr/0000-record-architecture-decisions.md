# ADR-0000: Record architecture decisions

- **Status:** Accepted
- **Date:** 2026-11-26

## Context

Provenance makes many consequential choices (runtime LLM, retrieval stack, storage, auth,
deployment) under hard constraints: zero cost, a ~5 GB local footprint, and a reviewer who must
be able to run it without friction. Reviewers and future maintainers need to see *why* each
choice was made, not only *what* was built.

## Decision

Record each significant decision as a short Architecture Decision Record in `docs/adr/`, numbered
sequentially, using the sections Context, Decision, Alternatives considered, Consequences. A
superseded ADR is kept and marked `Superseded by ADR-NNNN`.

## Consequences

- Decisions are reviewable in PRs alongside the code that implements them.
- Deviations from the PRD (for example, a different reranker) are explicit rather than silent.
