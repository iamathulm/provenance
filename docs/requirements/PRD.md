# Problem statement

Internal users need to find and verify answers across a changing collection of mixed documents. Manual search is slow, keyword search misses semantic matches, and uncited model answers are difficult to trust. Different teams may bring research papers or company documents tomorrow; a solution tuned to a single vocabulary or file layout would require costly rework.

Build a production-style capstone that ingests supported documents into private workspaces, retrieves authorized evidence, and produces grounded answers with usable citations. It must demonstrate adaptability and quality on at least two materially different domains, while operating within a documented free-tier budget. “Production-style” means disciplined engineering and demonstrated controls, not a claim of enterprise certification or guaranteed uptime.

### Definition of done

A reviewer can run the documented deployment and complete the core workflow; all mandatory FR/NFR gates pass or are explicitly marked failed; evaluation reports and data/config versions are reproducible; two domains meet their separate thresholds; threat/isolation, failure-injection, load, accessibility, unit, integration and end-to-end tests have documented results; CI builds and tests, CD deploys and smoke tests; README includes architecture, setup, operational runbook, known limits, data handling, quota/cost accounting and recovery.

# Target users and personas

**Primary audience:** internal users seeking answers from documents they are authorized to access. The deployment operator and reviewer are secondary users.

- **Maya, knowledge worker:** uploads project documents and asks questions in plain language. She needs quick, readable answers, clear uncertainty, citations that lead back to the source, and an understandable indication of indexing or failure.
- **Arun, capstone operator/reviewer:** configures the deployment and evaluates research and company-document collections. He needs tenant isolation, transparent retrieval diagnostics, measurable quality and latency, reproducible setup, and actionable operational metrics.


# Goals and non-goals

### Goals

1. Deliver the full workflow: authenticate, create a private workspace, upload and index documents, search, chat, inspect citations and review analytics.
2. Adapt to new document domains through configuration and evaluation, without domain-specific application code changes for the acceptance datasets.
3. Demonstrate retrieval, groundedness, isolation, responsiveness and recovery against the measurable targets below.
4. Provide an independently usable cloud baseline that stays usable while the development laptop is offline.
5. Make operation, quotas, failure modes and costs visible and reproducible.

### Non-goals

- Guaranteed zero latency, perfect answers, universal document understanding, or full OCR coverage.
- Training a foundation model, domain-specific fine-tuning, autonomous actions, or web-wide search.
- Enterprise compliance certification, high availability SLA, unrestricted scale or a promise of permanent free hosting.
- Shared team workspaces, enterprise SSO, granular document ACLs and connectors unless separately approved. The confirmed multi-user requirement is satisfied by private workspaces; shared access is an open decision.
- Pixel-perfect rendering or reliable extraction of all diagrams, equations, scanned pages, complex tables or speaker notes.



# Requirements and acceptance criteria

### Functional requirements

| ID | Requirement | Acceptance criteria |
|---|---|---|
| FR-01 | Authenticate and isolate users | A user can sign in/out and create/select a private workspace. Automated tests attempt cross-user access to documents, objects, vectors, chats, citations, search and analytics; all are denied, including direct IDs and service-mediated paths. |
| FR-02 | Manage documents | Upload supported types within configured limits; list status and metadata; replace and delete. An invalid, encrypted or oversized file gets an actionable error. Deletion immediately blocks retrieval and eventually removes original and derived data under NFR-07. |
| FR-03 | Parse and preserve provenance | Extract text from a representative digital PDF, DOCX, PPTX and UTF-8 TXT fixture; preserve correct PDF page / PPTX slide or available section anchors. Low or empty extraction is surfaced as partial/failed, never silently marked complete. Complex layouts and scans are explicitly qualified. |
| FR-04 | Index reliably | Jobs persist across worker restart, report queued/processing/ready/partial/failed, retry transient failures with bounded backoff, and are idempotent. Only a complete active version is searchable; failed replacement retains the prior active version. |
| FR-05 | Retrieve with hybrid ranking | Every query applies workspace and active-version filters to both Qdrant branches, fuses dense and sparse rankings via RRF, and attempts Voyage reranking. Simulated timeout/quota failure yields authorized RRF results with a visible fallback indicator. |
| FR-06 | Answer with evidence | A user can submit a question, see streaming or explicit progress, and receive an answer linked to source excerpts and anchors. On insufficient evidence the system says so, rather than presenting unsupported certainty; citations must reference retrieved, authorized active chunks. |
| FR-07 | Inspect and navigate sources | From an answer or Search Explorer, a user opens an authorized source preview and sees the cited excerpt and available page, slide or section. Missing anchors are labelled rather than fabricated. Revoked/deleted sources cannot be opened through old citations. |
| FR-08 | Explore search | Search Explorer accepts a query and document/type filters and displays authorized candidates, ranks, scores where available, source metadata and rerank/fallback mode. Empty results and provider failures are explained without leaking other workspaces. |
| FR-09 | Monitor and evaluate | Users can inspect workspace counts, job states, query timing and feedback; operators see aggregate health and quota/error indicators. A versioned evaluation command produces the metrics and breakdowns in section 8, including both domain datasets and RRF-only comparison. |
| FR-10 | Configure and deploy | A documented Compose setup starts the app, API and worker with configured dependencies; CI runs checks and builds images, and CD deploys an approved revision to a documented target. Cloud core passes smoke tests while the development laptop is offline. |

### Non-functional requirements

All timings below use a warm deployment, representative documents and non-exhausted quotas. Report cold starts, provider errors and failed requests separately; do not omit slow requests from percentiles. Targets are proposed, pending capacity and budget validation.

| ID | Requirement | Acceptance criteria |
|---|---|---|
| NFR-01 | Retrieval and answer quality | Meet the dataset, retrieval, citation and abstention targets in section 8 on each domain separately; publish failures and confidence intervals where sample size supports them. |
| NFR-02 | Interactive performance | In a 100-query test with 5 concurrent users, p95 retrieval ≤ 3 s and p95 time to first answer token ≤ 8 s; report end-to-end p50/p95 and provider failures. These are targets, not guarantees. |
| NFR-03 | Ingestion performance | On the documented target environment, ≥ 90% of 20 representative supported digital files of ≤ 20 pages each become searchable within 2 minutes of upload; exclude no failed jobs from the denominator and report rate limits separately. |
| NFR-04 | Security and isolation | TLS in transit; provider encryption at rest where available; server-side verified identity and workspace checks on every access, including object storage and both vector branches. Pass automated cross-tenant, ID manipulation and prompt-injection tests; no secrets in client bundles or logs. Treat retrieved text as untrusted data, never as instructions or authority. |
| NFR-05 | Availability and resilience | In failure-injection tests, a Voyage outage returns labelled RRF results; a local service outage uses deterministic rules; embedding, vector store or generation failures return an actionable error without invented answers. After worker restart, jobs resume without duplicate searchable chunks. No uptime SLA is claimed. |
| NFR-06 | Usability and accessibility | At 320 px, 768 px and desktop widths, core flows remain usable without horizontal page scrolling. Keyboard-only upload, search, chat and citation navigation work; automated checks show no critical WCAG 2.2 AA violations, supplemented by manual keyboard and contrast review. |
| NFR-07 | Privacy and data lifecycle | Private originals use controlled storage and short-lived authorized access. Revocation blocks reads immediately; deletion removes originals, chunks, vectors and derived artifacts within 24 hours in the test environment, with retry/audit state. Backup retention and provider-side retention are documented separately and remain open. No raw content in routine logs by default. |
| NFR-08 | Observability | Correlation IDs link upload, job and query events. Record status, stage durations, provider error class, retry count and estimated usage without raw document/question content by default; dashboard distinguishes success, failure and degraded rerank. |
| NFR-09 | Maintainability and portability | Versioned API contracts, parser/provider interfaces, pinned dependencies, migrations, configuration validation and reproducible containers are documented. Both domain profiles pass without domain-specific code changes. CI runs lint, unit, integration, isolation and end-to-end smoke tests. |
| NFR-10 | Budget and capacity | Before deployment, document every service's current free allowance, eligibility, payment-card requirement, region, data policy, hosting limits, expiry and expected usage. A representative capstone run must fit the verified allowances or be marked blocked/paid; set usage alerts and fail safely on quota exhaustion. Do not assume all components have a free tier. |
