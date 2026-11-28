# P5.1 Quality Gaps Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the measurable gaps found in the post-P5 audit before the frontend: an SQL execution-accuracy suite, a less trigger-happy query router, one time-boxed research-retrieval tuning pass, and two small correctness fixes. Then refresh every report.

**Architecture:**
- **SQL suite:** a new `evaluation/sql_eval.py` runs the real `generate_sql` and `run_query` for each table golden item. It executes a hand-written gold SQL through the same guarded engine and compares result sets.
- **Router:** keeps rules only. Weak superlative words now count only together with a top-ranked table chunk.
- **Retrieval tuning:** changes settings only, chosen on dev and reported on test.

**Tech Stack:** Python 3.12, uv, pytest, DuckDB, sqlglot guard, Groq through the cassettes in `eval/cassettes/answers`.

**Spec:** the audit and fix proposal in this session's chat, and `docs/superpowers/specs/2026-11-26-provenance-design.md` § "Automated evaluation" (target: SQL exact-match ≥ 0.80).

## Global Constraints

- Tune on `dev` only. `test` is reported and gated, and test labels are never edited to raise a score.
- The SQL suite adds at most 1 Groq call per table item. Every call is recorded in `eval/cassettes/answers` and committed, so CI replays it with no key.
- No question text or SQL in telemetry or logs. Evaluation uses `NullRecorder`.
- Retrieval p95 latency for `hybrid_rerank` must stay ≤ 3000 ms on the laptop (NFR-02 target).
- Write files with `newline="\n"`, no dead code (vulture), and keep ruff and mypy clean.
- Every commit ends with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. **Model returns no SQL** (`generate_sql` returns None): the item scores 0 with reason `no_sql` and does not crash the suite. Covered by a Task 1 test.
2. **Generated SQL is rejected by the guard or fails** (`AppError`): the item scores 0 with reason `error:<code>` and the run continues. Covered by a Task 1 test.
3. **Extra columns or different row order in the predicted result:** still a match if every gold row is contained in a distinct predicted row and the row counts are equal. Covered by a Task 1 test.
4. **Float noise** (`31.400000001` vs `31.4`) and **case** (`'Engineering'` vs `'engineering'`): equal after normalization (numbers rounded to 2 dp, strings casefolded and stripped). Covered by a Task 1 test.
5. **Concurrent identical feedback PUTs:** both succeed and leave one row. Covered by a Task 4 test.

---

### Task 1: SQL execution-accuracy suite

**Files:**
- Modify: `apps/api/src/provenance/evaluation/golden.py` (`GoldenItem.sql: str | None = None`)
- Modify: `eval/golden/company/dev.yaml` and `eval/golden/company/test.yaml` (add `sql:` to every `category: table` item: 4 dev, 5 test)
- Create: `apps/api/src/provenance/evaluation/sql_eval.py`
- Modify: `apps/api/src/provenance/evaluation/report.py` (`check_sql_threshold`)
- Modify: `apps/api/src/provenance/cli.py` (`--suite sql`)
- Modify: `eval/thresholds.yaml` (top-level `sql:` section)
- Modify: `.github/workflows/ci.yml` (`eval` job step)
- Test: `apps/api/tests/evaluation/test_sql_eval.py`, `apps/api/tests/evaluation/test_golden.py`

**Interfaces:**
- Consumes: `generate_sql(llm, ctx, prompt, model, question, entries) -> str | None` (`answers/sql.py`); `run_query(db, workspace_id, sql, settings) -> QueryResult` (`structured/engine.py`); `load_catalog(db, workspace_id)`; `workspace_for(db, domain)`; `EvalRuntime` (`.llm`, `.sessions`, `.settings`); `bootstrap_ci`, `Estimate`, `mean` as used in `evaluation/retrieval.py`; `write_report`; `run_metadata`.
- Produces:
  - `normalize_value(value: Value) -> Value`
  - `results_match(gold: QueryResult, predicted: QueryResult) -> bool`
  - `@dataclass SqlRecord(id: str, match: bool, reason: str, sql: str | None)`, where reason is one of `match`, `mismatch`, `no_sql`, `error:<code>`
  - `@dataclass SqlReport(domain, split, items: list[SqlRecord], metrics: dict[str, Estimate])`, with the metric key `execution_accuracy`
  - `async evaluate_sql(session_factory, llm: LLMClient, settings: Settings, golden: GoldenSet) -> SqlReport`
  - `sql_json(reports, metadata) -> dict` and `sql_markdown(reports, metadata) -> str`
  - `check_sql_threshold(reports: list[SqlReport], thresholds: dict) -> list[str]`, which reads `thresholds["sql"][domain]`

**Steps:**

- [ ] **Step 1: Write failing tests** in `test_sql_eval.py`. Build `QueryResult` values by hand; no DB is needed for the comparison tests.
  - `test_match_ignores_row_order_extra_columns_and_row_column`:
    - gold `columns=["mode","n"]`, rows `[["Battery swelling",21]]`
    - predicted `columns=["_row","failure_mode","claims","share"]`, rows `[[4,"battery swelling",21.0,0.5]]`
    - Expect `results_match` is True.
  - `test_float_noise_and_case_are_equal`: `31.400000001` vs `31.4`, and `" Engineering"` vs `"engineering"`. Expect True.
  - `test_row_count_mismatch_fails`: gold has 1 row, predicted has 2 rows that both contain it. Expect False.
  - `test_wrong_value_fails`: `47` vs `46`. Expect False.
  - `test_each_gold_row_needs_its_own_predicted_row`: gold `[[1],[1]]`, predicted `[[1],[2]]`. Expect False.
  - `async test_evaluate_sql_scores_and_survives_failures(indexed harness with an xlsx table)`:
    - A `ScriptedProvider` (from `tests/generation/fakes`) returns, in turn:
      - a correct SQL JSON
      - `{"answerable": false, "sql": ""}`
      - a `DROP TABLE` SQL
    - Expected reasons: `["match", "no_sql", "error:sql_rejected"]`.
    - Expected `execution_accuracy.mean == 1/3`.
    - Reuse the `HEADCOUNT` workbook pattern from `tests/answers/test_cassette_e2e.py` and the harness fixtures used by `tests/evaluation/test_answers_eval.py`.
    - Use the guard's real rejection code. Check `structured/sql_guard.py` and use its `AppError.code` verbatim.
  - `test_check_sql_threshold`: a report with 0.5 against `{"sql": {"company": 0.8}}` returns 1 failure string `company/test execution_accuracy 0.500 < 0.80`. Domains missing from `sql:` are skipped.
  - In `test_golden.py`, add `test_table_items_carry_gold_sql`: every `category: table` item in both company splits has a non-empty `sql` starting with `SELECT`.

- [ ] **Step 2: Run** `uv run pytest apps/api/tests/evaluation/test_sql_eval.py apps/api/tests/evaluation/test_golden.py -q`. Expected: FAIL (import error, missing field).

- [ ] **Step 3: Implement** `sql_eval.py` and the golden `sql` field.
  - Comparison: drop the `_row` column from both sides, then map each row to a `Counter` of normalized values. Match when row counts are equal and a greedy assignment gives every gold row a distinct predicted row whose `Counter` contains it.
  - `normalize_value`: bool stays as is; int and float become `round(float(v), 2)`; str becomes `casefold().strip()`; None stays.
  - `evaluate_sql`:
    - Runs only items with `category == "table"`.
    - One `RequestContext(correlation_id=f"eval-sql-{item.id}", workspace_id=...)` per item.
    - Calls `generate_sql` with `load_prompt("sql")` and `settings.sql_model`.
    - Runs gold and predicted SQL with `run_query`, using a fresh session each time.
    - A gold SQL failure is a bug: raise it.
    - Catches `AppError` around predicted generation and execution, and records `error:<code>`.
  - Metric: `execution_accuracy` = mean of matches, with a bootstrap CI.

- [ ] **Step 4: Write gold SQL** for the 9 items.
  - Get table names first: run `uv run provenance seed-demo --with-corpora` if the DB is empty, then call `GET /v1/workspaces/{id}/tables`, or run a scratch script around `load_catalog`.
  - Select only the columns the question asks for (for "Which failure mode has the most claims", the mode and the count).
  - Check each gold SQL returns the item's `reference` value. Add a test, `test_gold_sql_reproduces_references`, marked with the same DB-and-corpus marker the retrieval gate uses. If no such marker exists, do the check by hand once and note it in the commit message instead of adding the test.

- [ ] **Step 5: Wire up the command and the gate.**
  - CLI: `--suite sql` reuses `--domain`, `--split`, `--out` and `--check`.
  - It runs inside `eval_runtime(settings, use_judge=False)`, writes `sql-<split>.{json,md}`, and its exit code is the gate's.
  - In `thresholds.yaml`, add `sql: {company: <floor>}` with the floor 0.05 below the first committed test score, rounded down, and never above 0.80. Comment it the same way as the retrieval floors.
  - In `ci.yml`, after the retrieval gate, add the step `uv run provenance eval --suite sql --split test --domain company --out eval-report --check eval/thresholds.yaml`.

- [ ] **Step 6: Record and run** `uv run provenance eval --suite sql --split dev --domain company --out eval/reports`, then the same with `--split test`. The key comes from `.env`, so new cassettes are recorded. Then run it again with `GROQ_API_KEY=` empty: it must replay and give identical scores.

- [ ] **Step 7: Verify** `uv run pytest apps/api/tests/evaluation -q`, `uv run ruff check .`, `uv run mypy` and `uv run vulture`. All clean.

- [ ] **Step 8: Commit** `feat(eval): SQL execution-accuracy suite with gold queries and CI gate`. Include the new cassettes and the `sql-*` reports.

### Task 2: Router precision

**Files:**
- Modify: `apps/api/src/provenance/retrieval/router.py`
- Modify: `apps/api/src/provenance/evaluation/retrieval.py` (`ItemResult.route_reasons: list[str]`)
- Modify: `apps/api/src/provenance/evaluation/report.py` (a "Route misses" table in the markdown: id, expected, predicted, reasons)
- Test: `apps/api/tests/retrieval/test_router.py`, `apps/api/tests/evaluation/test_metrics.py` or the existing report test

**Interfaces:**
- Consumes: `route_query(question, chunks, workspace_has_tables) -> Route` (the signature is unchanged).
- Produces:
  - `STRONG_AGGREGATE` and `WEAK_AGGREGATE` module patterns.
  - `TABLE_HIT_WINDOW`, whose value is decided in Step 3.
  - `Route.reasons` gains the prefixes `strong aggregate`, `weak aggregate` and `table chunk at rank N`.

**Steps:**

- [ ] **Step 1: Write failing tests.**
  - Report test: a route-miss row renders its reasons.
  - New router parametrize cases. The existing cases must keep passing.
    - `("What is the maximum payload of the Talon X2?", DOCS_ONLY, True, "docs")`: a weak word alone is not a computation.
    - `("Which failure mode has the most warranty claims?", TABLE_TOP, True, "table")`: weak word plus a top table hit.
    - `("Which month of Q3 had the highest revenue?", TABLE_TOP, True, "table")`
    - `("How many support tickets were opened for the Harrier Mini in Q3?", TABLE_TOP, True, "table")`
    - `("What ingress protection rating does the Sentinel Dock have?", [chunk("page"), chunk("page"), chunk("page"), chunk("rows")], True, "docs")`: a table chunk at rank 4 is not a table hit.
  - Strong words: `how many, how much, total, sum, average, avg, mean, median, count, number of, top N, bottom N, per <dim>, by <dim>, percent, share of`, and the comparison phrases.
  - Weak words: `highest, lowest, largest, smallest, most, least, maximum, minimum, max, min, rank, ranking`.
  - New decision rule:
    - strong + table hit → `table`
    - weak + table hit → `table`
    - strong alone → `both`
    - table hit alone → `both`
    - weak alone → `docs`
    - nothing → `docs`

- [ ] **Step 2: Run** `uv run pytest apps/api/tests/retrieval/test_router.py -q`. Expected: the new cases FAIL.

- [ ] **Step 3: Implement**, then tune on dev only.
  - Run `uv run provenance eval --split dev`. Read the new "Route misses" section and set `TABLE_HIT_WINDOW` to 3, or keep 5, whichever gives higher company dev route accuracy.
  - Acceptance: every dev `category: table` item still routes to `table` or `both`.
  - Do not add question-specific words to fix single items.

- [ ] **Step 4: Run** the router and eval tests, then `uv run provenance eval --split test --ablation --out eval/reports --check eval/thresholds.yaml` and `--split dev --ablation --out eval/reports`. Record the test route accuracy before and after in the commit body (before: company 0.67 test, 0.76 dev).

- [ ] **Step 5: Check the answer cassettes.** A route change from `both` to `docs` drops a SQL call, and it also changes the answer prompt, because the SQL rows disappear from the sources.
  - Run `uv run pytest apps/api/tests/answers/test_cassette_e2e.py -q`.
  - If it fails on a cassette miss, re-record with `RECORD_CASSETTES=1` (key in `.env`), then rerun it without the key.

- [ ] **Step 6: Commit** `feat(retrieval): route weak superlatives to tables only with a top-ranked table hit`. Include the refreshed `retrieval-*` reports and any re-recorded e2e cassettes.

### Task 3: Research retrieval tuning (time-boxed, settings only)

**Files:**
- Modify: `apps/api/src/provenance/core/config.py` (`rerank_max_tokens`, `rerank_candidates` defaults)
- Modify: `profiles/research.yaml` (only the comment about reranker token limits)
- Modify: `eval/thresholds.yaml` (raise floors only if the baseline improves)
- Reports: `eval/reports/retrieval-{dev,test}.{json,md}`

**Interfaces:**
- Consumes: `Settings.rerank_max_tokens` (256) and `Settings.rerank_candidates` (20), both overridable from the environment as `RERANK_MAX_TOKENS` and `RERANK_CANDIDATES`.
- Produces: new defaults only. No code paths change.

**Steps:**

- [ ] **Step 1: Run the grid on dev.** Use env overrides and skip `--out`, so the committed reports stay untouched until the choice is made:
  - `rerank_max_tokens` ∈ {256, 384, 512}
  - `rerank_candidates` ∈ {20, 30}
  - The command for each cell is `uv run provenance eval --split dev`.
  - Record a table with research and company recall@5, MRR@10, and hybrid_rerank p95 latency for each cell.

- [ ] **Step 2: Choose.**
  - Pick the cell with the highest research dev (recall@5 + MRR@10).
  - It must not drop company dev recall@5 or MRR@10 by more than 0.02.
  - Its p95 latency must be ≤ 3000 ms.
  - If no cell beats 256/20 by at least 0.02 on that sum, keep the defaults and record the result as a documented negative finding.

- [ ] **Step 3: Apply and measure.** Set the chosen defaults in `config.py` and run `uv run pytest apps/api/tests/retrieval -q`.
  - Expected: PASS. Tests that use `FakeReranker` are unaffected.
  - If a test pins 256 or 20, update it to the new default.

- [ ] **Step 4: Refresh reports.**
  - Run `uv run provenance eval --split test --ablation --out eval/reports --check eval/thresholds.yaml` and the dev equivalent.
  - If the test baseline rose, raise the floors in `thresholds.yaml` to about 0.05 under the new baseline.

- [ ] **Step 5: Commit** `perf(retrieval): rerank settings tuned on dev for research passages` or, if the defaults were kept, `docs(eval): record rerank grid (no change)`. Put the grid table in the commit body.

### Task 4: Small correctness fixes

**Files:**
- Modify: `apps/api/src/provenance/analytics/router.py:30`
- Modify: `apps/api/src/provenance/conversations/feedback.py` (`set_feedback`)
- Test: `apps/api/tests/analytics/test_analytics_api.py`, `apps/api/tests/conversations/test_feedback.py`

**Interfaces:**
- Consumes: `Settings.operator_emails: list[str]` and the `Feedback` unique constraint on `(message_id, user_id)`.
- Produces: `set_feedback` keeps its signature and return type.

**Steps:**

- [ ] **Step 1: Write failing tests.**
  - `test_operator_email_match_ignores_case`: with `operator_emails=["Demo@Provenance.Local"]`, the demo user gets 200.
  - `test_concurrent_feedback_upserts_one_row`:
    - Two `set_feedback` calls on separate sessions for the same message and user, run with `asyncio.gather`.
    - Both commit without `IntegrityError`.
    - Exactly 1 `Feedback` row is left, and its rating is one of the two.

- [ ] **Step 2: Run them.** Expected: FAIL (403 for the first test; `IntegrityError` for the second).

- [ ] **Step 3: Implement.**
  - Compare `user.email.casefold()` with a casefolded set of the operator emails.
  - Replace the select-then-add in `set_feedback` with a PostgreSQL `insert(...).on_conflict_do_update(index_elements=[Feedback.message_id, Feedback.user_id], set_={rating, comment})`, the same pattern as `conversations/cache.put_cached`. Then load and return the row.

- [ ] **Step 4: Verify** `uv run pytest apps/api/tests/analytics apps/api/tests/conversations -q`. Expected: PASS.

- [ ] **Step 5: Commit** `fix(api): case-insensitive operator emails; atomic feedback upsert`.

### Task 5: Refresh answer reports, docs and PR

**Files:**
- Reports: `eval/reports/answers-{dev,test}.*` (only if Tasks 2–3 changed the answer prompts, in which case the old cassettes are now orphaned)
- Modify: `docs/eval-report.md`, `docs/progress.md` (a P5.1 section), `docs/adr/0009-evaluation-design.md` (the SQL suite row in the suites table)

**Steps:**

- [ ] **Step 1: Rerun the answers suite.** Run `uv run --group eval provenance eval --suite answers --split test --limit 10 --out eval/reports` and the dev equivalent.
  - New requests record, about 20 Groq answers.
  - Then delete cassette files no current request uses. The cassette loader keys files by SHA, so list them by modified time and diff the keys the runs used.
  - Rerun without the key to confirm replay.

- [ ] **Step 2: Update the docs.**
  - `eval-report.md`:
    - Add an SQL section with execution accuracy and its CI per split.
    - Update the retrieval and answer numbers and the router accuracy.
    - Correct the research-miss explanation: most misses are passage ranking inside the right paper, not multi-hop.
  - `progress.md` P5.1: what changed, the measured before and after, gotchas (gold SQL selects only the asked-for columns; route changes invalidate answer cassettes).

- [ ] **Step 3: Full verification.** Run `uv run pytest -q`, `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy`, `uv run vulture` and `uv run alembic -c apps/api/alembic.ini check`. All must be clean.

- [ ] **Step 4: Commit** `docs(eval): P5.1 reports and progress`. Then push, open a PR to `main` titled "P5.1: SQL execution accuracy, router precision, rerank tuning", with the before and after metrics table in the body, and run a final whole-branch review.
