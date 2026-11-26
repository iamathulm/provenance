# P2 Ingestion + Corpora Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Users upload PDF/DOCX/PPTX/TXT/CSV/XLSX files into a workspace; a persistent worker validates, parses (with page/slide/section/row anchors), chunks per domain profile, embeds (dense + BM25) and indexes them into Qdrant; versions activate atomically; replace and delete follow the PRD lifecycle; two demo corpora (synthetic company KB, CC-BY research papers) index via configuration only.

**Architecture:** `documents/` owns documents, versions and their HTTP API. `ingest/` owns validation, parsers, chunking, the Postgres job queue and the worker. `retrieval/index.py` owns embeddings and the Qdrant collection. `profiles/*.yaml` drive chunking per workspace. The worker runs the indexing job as `Pipeline` stages (P1 core) so every stage is timed and recorded.

**Tech Stack:** PyMuPDF 2.2, python-docx 1.2, python-pptx 1.0, openpyxl 3.1, pyarrow 26, FastEmbed 0.9 (`BAAI/bge-small-en-v1.5` 384-d, `Qdrant/bm25` sparse), qdrant-client 1.20, python-multipart.

**Spec:** `docs/superpowers/specs/2026-11-26-provenance-design.md` (P2 row, Orchestration/ingestion pipeline, RAG core, FR-02/03/04, NFR-03/05/07).

## Global Constraints

- All P0/P1 constraints hold. Every new workspace-scoped route depends on `OwnedWorkspace`; `document_id` joins `KNOWN_PARAMETERS` in the isolation suite.
- Supported types (by magic bytes, extension must agree): `.pdf`, `.docx`, `.pptx`, `.txt` (UTF-8), `.csv` (UTF-8), `.xlsx`. Max 10 MB, max 200 PDF pages / slides, max 50 000 table rows per file.
- Upload error codes (422 unless noted): `unsupported_type`, `type_mismatch`, `empty_file`, `encrypted_file`, `corrupt_file`, `not_utf8`, `too_many_pages`, `too_many_rows`, `file_too_large` (413). Messages tell the user what to do.
- Version statuses: `queued → processing → ready | partial | failed`. Processing stage shown to users: `parsing`, `chunking`, `embedding`, `indexing`. `partial` = indexed but with extraction warnings (e.g. pages with no extractable text).
- A page/slide yielding < 20 characters of text is a warning; a document where > 50% of pages are below that is `partial` with warning `low_text_extraction` ("This looks scanned; OCR is not supported").
- Anchors: PDF `page` (1-based), PPTX `slide` (1-based, speaker notes excluded and stated), DOCX `section` (heading path), TXT `section` (heading path, else line range), CSV/XLSX `rows` (sheet + 1-based data-row range). Missing anchor = `none`, never invented.
- Chunking per profile: `target_tokens`, `overlap_tokens`, `max_tokens`; token count = whitespace word count (documented approximation). Chunks never cross a page/slide boundary or a table row group; table row groups repeat the header.
- Qdrant collection `chunks`: named dense vector `dense` (384, cosine), sparse vector `bm25` (IDF modifier); payload `workspace_id`, `document_id`, `version_id` (keyword indexes), `active` (bool index). Point ID = chunk UUID (idempotent upserts).
- Only the active, ready/partial version of a non-deleted document is searchable; deletion sets `deleted_at` and deactivates points immediately, then a purge job removes chunks, vectors, tables and files with audit rows.
- Jobs: lease 60 s, heartbeat every 15 s, `max_attempts = 5`, backoff `min(2 ** attempt, 60)` seconds; transient errors (connection, timeout) retry, permanent errors (parse/validation) fail the version immediately. Re-running a job first deletes that version's existing chunks and points (no duplicates).
- Company: fictional "Kestrel Ridge Systems" (industrial drone maker). Research corpus: CC BY 4.0 arXiv papers ≤ 20 pages, license and SHA-256 recorded per paper, fetched by script (not committed).
- Profiles are configuration: adding `profiles/<name>.yaml` must be enough to add a domain (no code change); the workspace profile validator reads the loaded profiles.

## Review Focus

- **Same file uploaded twice / worker crash mid-job:** exactly one set of chunks and points — `test_rerun_after_crash_leaves_no_duplicates` (Task 7).
- **Replacement that fails to parse:** previous version stays active and searchable — `test_failed_replacement_keeps_prior_version_active` (Task 8).
- **Renamed file (`report.pdf` that is really a ZIP, `.txt` with binary content):** actionable 422, no job queued — `test_type_mismatch_and_binary_txt_rejected` (Task 3).
- **Spreadsheet with empty rows, merged header cells or formulas:** rows anchored correctly, empty rows skipped, formula *values* indexed — `test_xlsx_values_and_row_anchors` (Task 4).
- **Deleted document cited by an old chat link:** chunk lookup returns 404 immediately after delete, before purge runs — `test_delete_blocks_reads_before_purge` (Task 8).

---

### Task 1: Domain profiles

**Files:** create `profiles/company.yaml`, `profiles/research.yaml`, `apps/api/src/provenance/profiles/{__init__,loader,router}.py`; modify `core/config.py` (`profiles_dir: Path` default repo `profiles/`), `workspaces/router.py` (profile validated against loaded names; PATCH accepts `profile`), `api/app.py` (load at startup into `app.state.profiles`); tests `tests/profiles/test_profiles.py`.

**Interfaces — Produces:**
- `DomainProfile(BaseModel)`: `name: str`, `display_name: str`, `description: str`, `chunking: ChunkingConfig(target_tokens: int, overlap_tokens: int, max_tokens: int, table_rows_per_chunk: int)`.
- `load_profiles(directory: Path) -> dict[str, DomainProfile]` (fails fast on invalid YAML/schema; name must equal file stem).
- `GET /v1/profiles` → list of `{name, display_name, description}` (authenticated).
- Values: company `350/50/500/20`, research `450/80/650/15`.
- [ ] Tests: both shipped profiles load; a third YAML in a temp dir is picked up without code change; bad schema raises; creating a workspace with an unknown profile → 422; `GET /v1/profiles` requires auth.
- [ ] Commit `feat(profiles): load domain profiles from configuration`.

### Task 2: Document, version, chunk, table, job and audit tables

**Files:** create `documents/models.py` (`Document`, `DocumentVersion`, `Chunk`, `VersionTable`), `ingest/models.py` (`Job`), `audit/models.py` (`AuditEvent`); register in `db/models.py`; migration `0005_documents`.

**Interfaces — Produces:**
- `Document`: `id`, `workspace_id` (FK cascade, index), `title`, `filename`, `media_type`, `active_version_id` (nullable, FK `document_versions.id`, `use_alter`), `deleted_at` (nullable), `created_at`.
- `DocumentVersion`: `id`, `document_id` (FK cascade), `workspace_id`, `number` (unique per document), `stored_file_id` (FK `stored_files`), `status`, `stage` (nullable), `error_code`/`error_message` (nullable), `page_count`, `chunk_count`, `warnings` (JSONB list of `{code, message, anchor}`), `created_at`, `completed_at`.
- `Chunk`: `id`, `version_id` (FK cascade, index), `workspace_id`, `document_id`, `ordinal`, `text`, `token_count`, `anchor_kind`, `anchor_label`, `page`, `slide`, `section_path`, `sheet`, `row_start`, `row_end`.
- `VersionTable`: `id`, `version_id` (FK cascade), `workspace_id`, `name`, `stored_file_id` (Parquet), `row_count`, `columns` (JSONB).
- `Job`: `id`, `kind`, `workspace_id`, `version_id` (nullable), `document_id` (nullable), `status` (`queued|running|succeeded|failed`), `attempts`, `max_attempts`, `run_after`, `locked_by`, `locked_until`, `last_error_class`, `idempotency_key` (unique), timestamps; index on `(status, run_after)`.
- `AuditEvent`: `id`, `workspace_id`, `actor_user_id` (nullable), `action`, `subject_id`, `detail` (JSONB), `created_at`.
- [ ] Test: `alembic check` clean; migration round-trip test still passes.
- [ ] Commit `feat(documents): add document, version, chunk, table, job and audit tables`.

### Task 3: Upload validation

**Files:** create `ingest/validation.py`; test `tests/ingest/test_validation.py` (fixtures built in code: PDF via PyMuPDF incl. encrypted, DOCX/PPTX/XLSX via their libraries, zip bomb-ish ZIP, binary `.txt`).

**Interfaces — Produces:** `FileKind = Literal["pdf","docx","pptx","txt","csv","xlsx"]`; `ValidatedFile(kind, filename, media_type, content)`; `validate_upload(filename: str, content: bytes, settings) -> ValidatedFile` raising `UploadRejectedError(AppError)` with the codes above.
- [ ] Tests: one valid file per kind accepted with correct media type; `test_type_mismatch_and_binary_txt_rejected`; encrypted PDF; truncated PDF; empty file; unknown extension; Latin-1 CSV → `not_utf8`; over-size → 413.
- [ ] Commit `feat(ingest): validate uploads by content, not extension`.

### Task 4: Parsers

**Files:** create `ingest/parsers/{__init__,base,pdf,docx,pptx,text,tables}.py`; tests `tests/ingest/test_parsers.py`.

**Interfaces — Produces:**
- `Anchor(kind: Literal["page","slide","section","rows","none"], label: str, page: int|None, slide: int|None, section_path: str|None, sheet: str|None, row_start: int|None, row_end: int|None)`.
- `Block(text: str, anchor: Anchor, is_table: bool)`; `ParsedTable(name: str, columns: list[str], rows: pyarrow.Table)`; `ParseWarning(code, message, anchor: Anchor|None)`.
- `ParsedDocument(title: str, blocks: list[Block], tables: list[ParsedTable], unit_count: int, warnings: list[ParseWarning])`.
- `parse(validated: ValidatedFile, profile: DomainProfile) -> ParsedDocument` dispatching by kind. Table parsers emit one *table card* block (name, columns, row count, first 3 rows) plus row-group blocks of `table_rows_per_chunk` rows with header repeated.
- [ ] Tests: PDF page anchors + low-text warning on an image-only page; DOCX heading path (`Leave policy > Parental leave`); PPTX slide anchors, notes not indexed; TXT markdown headings → section path, otherwise line ranges; CSV row anchors; `test_xlsx_values_and_row_anchors` (formula cached values, empty rows skipped, one table per sheet).
- [ ] Commit `feat(ingest): parse PDF, DOCX, PPTX, TXT, CSV and XLSX with provenance anchors`.

### Task 5: Chunking

**Files:** create `ingest/chunking.py`; test `tests/ingest/test_chunking.py`.

**Interfaces — Produces:** `ChunkDraft(ordinal, text, token_count, anchor)`; `chunk_document(parsed: ParsedDocument, config: ChunkingConfig) -> list[ChunkDraft]` — merges consecutive blocks sharing an anchor up to `target_tokens`, splits longer runs into windows of `target_tokens` with `overlap_tokens` overlap on sentence boundaries where possible, never exceeds `max_tokens`, never merges across anchors, keeps table blocks whole.
- [ ] Tests: no chunk crosses pages; overlap present between consecutive windows; max respected; table blocks untouched; ordinals contiguous; empty blocks dropped.
- [ ] Commit `feat(ingest): profile-driven, anchor-preserving chunking`.

### Task 6: Embeddings and Qdrant index

**Files:** create `retrieval/__init__.py`, `retrieval/embeddings.py`, `retrieval/index.py`; modify `core/config.py` (`embedding_model`, `sparse_model`, `fastembed_cache_dir`); tests `tests/retrieval/test_index.py` (real Qdrant, deterministic fake embedder).

**Interfaces — Produces:**
- `Embedder` Protocol: `dense(texts: list[str]) -> list[list[float]]`, `sparse(texts: list[str]) -> list[SparseVector]`; `FastEmbedder(settings)` (lazy model load, thread offload via `asyncio.to_thread`).
- `ChunkIndex(client: AsyncQdrantClient, collection="chunks")`: `ensure_collection()`, `upsert(points: list[IndexPoint])`, `delete_version(version_id)`, `set_active(version_id, active: bool)`, `set_document_active(document_id, active: bool)`, `count(version_id) -> int`.
- `IndexPoint(chunk_id, workspace_id, document_id, version_id, dense, sparse, active)`.
- [ ] Tests: ensure_collection idempotent with payload indexes; upsert same IDs twice → count unchanged; delete_version; set_active flips payload. One `@pytest.mark.slow` test runs real FastEmbed on two sentences (CI caches models).
- [ ] CI: add `qdrant/qdrant:v1.20.2-unprivileged` service and cache `~/.cache/fastembed`.
- [ ] Commit `feat(retrieval): dense + BM25 embeddings and Qdrant chunk index`.

### Task 7: Job queue, indexing job and worker

**Files:** create `ingest/jobs.py`, `ingest/indexing.py` (stages), `ingest/worker.py`; modify `cli.py` (`provenance worker`); tests `tests/ingest/test_jobs.py`, `test_indexing.py`.

**Interfaces — Produces:**
- `enqueue(db, kind, workspace_id, *, version_id=None, document_id=None, idempotency_key) -> Job` (existing key → returns existing job).
- `claim_next(db, worker_id, lease_s=60) -> Job | None` (`FOR UPDATE SKIP LOCKED`; reclaims `running` jobs whose lease expired); `heartbeat(db, job, lease_s)`; `complete(db, job)`; `fail(db, job, error, *, transient: bool)`.
- `IndexVersionJob` = stages `Parse → Chunk → Embed → Index → Activate`, each a `Stage` updating `version.stage`; `run_index_job(ctx, deps, job)`.
- `Worker(session_factory, deps, worker_id).run(stop: asyncio.Event)` and `.run_until_idle()` (used by tests and the seed command).
- [ ] Tests: two concurrent claims never get the same job; expired lease reclaimed; transient failure → requeued with backoff, attempts++; permanent failure → version `failed` with user-safe `error_message`; `test_rerun_after_crash_leaves_no_duplicates`; stage spans recorded per stage.
- [ ] Commit `feat(ingest): persistent job queue and indexing worker`.

### Task 8: Document API and lifecycle

**Files:** create `documents/service.py`, `documents/router.py`; extend isolation suite (`document_id`); tests `tests/documents/test_documents_api.py`.

**Interfaces — Produces:**
- `POST /v1/workspaces/{workspace_id}/documents` (multipart `file`) → 202 `DocumentOut` (status `queued`).
- `GET /v1/workspaces/{workspace_id}/documents?status=` → list; `GET …/documents/{document_id}` → detail with versions, warnings, chunk count, `stored_file_id` for link creation.
- `POST …/documents/{document_id}/versions` (multipart replace) → 202.
- `POST …/documents/{document_id}/retry` → 202 (latest version failed only, else 409).
- `DELETE …/documents/{document_id}` → 202; immediately hidden from list/detail/chunks (404), points deactivated, purge job queued, audit rows `document.delete_requested` / `document.purged`.
- `GET …/documents/{document_id}/chunks?offset&limit` → chunk previews (text, anchor) of the active version.
- Activation: new version ready → Qdrant activate new, set `active_version_id`, commit, deactivate old.
- Workspace profile change (PATCH) → reindex job per active version (new version reusing the stored file).
- [ ] Tests: upload → worker → `ready` with chunks; list/status filter; `test_failed_replacement_keeps_prior_version_active`; successful replacement swaps active; `test_delete_blocks_reads_before_purge`; purge removes chunks, points, files and writes audit; retry; profile change reindexes; isolation suite passes with new routes.
- [ ] Commit `feat(documents): upload, replace, retry and delete with atomic version activation`.

### Task 9: Demo corpora

**Files:** create `data/company/source/*.yaml` (authored content), `scripts/build_company_corpus.py` (deterministic render to PDF/DOCX/PPTX/TXT/CSV/XLSX under `data/company/files/`), generated files committed; `data/research/manifest.yaml` (arXiv id, title, authors, license `CC BY 4.0`, pages, sha256), `scripts/fetch_research_corpus.py` (downloads to `data/research/files/`, verifies sha256, git-ignored); modify `seed.py` / `cli.py` (`seed-demo --with-corpora` uploads both corpora and drains the worker).
- Company KB (~24 files): HR handbook + leave policy (PDF), IT runbooks + incident postmortems (TXT, markdown-style), product specs (DOCX), quarterly review deck (PPTX), pricing + sales + support tickets (CSV/XLSX), vendor FAQ containing an embedded prompt-injection line (poisoned doc for P4).
- Research: 8–10 CC BY 4.0 retrieval/RAG papers, licenses verified on arxiv.org before inclusion.
- [ ] Tests: build script is deterministic (two runs → identical hashes); every generated file passes `validate_upload`; manifest entries all `CC BY 4.0` with sha256.
- [ ] Measure: seed both corpora locally; record files, chunks, wall time in `docs/progress.md` (target < 2 min for 20 files).
- [ ] Commit `feat(data): add Kestrel Ridge company corpus and CC BY research manifest`.

### Task 10: PR, review, report

- [ ] `docs/progress.md` P2 handoff; ADRs `0002-postgres-job-queue.md`, `0003-postgres-file-storage.md`.
- [ ] Push, PR, CI green, whole-branch review, fixes, report.
