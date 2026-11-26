# Provenance — Enterprise Production-Grade RAG Product Design Brief

**Status:** Design specification for implementation · 26 November 2026

**Inputs:** Product requirements in `PRD.md` and the formal design system specification in `GETDESIGN.MD`. “Provenance” remains the working product name. All UI surfaces, tokens, typography, geometry, and interactive primitives are governed by `GETDESIGN.MD`, with explicit system extensions documented where enterprise RAG workflows exceed `GETDESIGN.MD`’s public-surface scope.

---

## 1. Design Principles

1. **Put evidence beside the answer.** Every substantive answer makes its sources immediately discoverable, exposing the verbatim excerpt, document title, and page/slide/section anchor in a single action. Answers that cannot be substantiated state so explicitly.
2. **Make system progress and limits legible.** Surface real ingestion stages (queued, parsing, chunking, embedding, indexed), retrieval modes (hybrid dense/sparse, reranked, or RRF fallback), unavailable sources, and actionable errors in plain language. Never imply a document is searchable before indexing completes.
3. **Give reading priority over decoration.** Anchor the workspace on `{colors.canvas}` (`#f9f7f3`) with strict typographic lanes (`rb-freigeist-neue`, `basier-square`, `jetbrains-mono`), pill-shaped interactive controls (`{rounded.full}`), rectangular reading/evidence cards (`{rounded.md}` / `{rounded.lg}`), and single-stamp `{colors.primary}` (`#ea2804`) discipline so long answers and citations remain the visual focus.

---

## 2. Visual Direction

**Mood:** A calm research desk with zine-like editorial precision—warm cream paper (`{colors.canvas}`), warm charcoal ink (`{colors.ink}`), crisp hairline rules (`{colors.hairline}`), dark printed pull-quotes for code and retrieval diagnostics (`{colors.surface-dark}`), and a single hot-orange stamp (`{colors.primary}`) per viewport.

**Structural Rhythm & Geometry:**

* **Color-blocking over shadows:** Elevation is achieved through surface shifts (`{colors.canvas}` → `{colors.surface-bone}` → `{colors.surface-card}` → `{colors.surface-dark}`) separated by `1px` `{colors.hairline}` rules rather than drop shadows on cream.
* **Pill-vs-card contrast:** Every interactive control—buttons, search inputs, filter pills, status badges, and avatars—uses `{rounded.full}` (`9999px`). Content containers, evidence cards, drawers, and diagnostic code wells step to `{rounded.md}` (`10px`) or `{rounded.lg}` (`16px`). Sharp `0px` corners (`{rounded.none}`) are restricted to full-bleed bands (`{component.hero-band}`, `{component.footer}`).
* **Dark code & trace wells:** All generated SQL/structured queries, raw chunk payloads, reranker scores, and API snippets render inside `{component.code-block}` (`{colors.surface-dark}`), never in light-grey inline boxes.

**Avoid:**

* Pure-white (`#ffffff`) page backgrounds; reserve `{colors.surface-card}` strictly for individual cards, inputs, and overlay drawers.
* More than one `{colors.primary}` (`#ea2804`) element per viewport; demote secondary CTAs to `{component.button-dark}` or `{component.button-outline}`.
* `{rounded.full}` on content cards, answer blocks, or multiline composers.
* Loosening display `lineHeight` past `1.0`, bumping body font weight to `500` for emphasis, or setting code/diagnostics in `basier-square`.
* Gradients, glowing AI motifs, robot imagery, invented confidence percentages, or color-only status indicators.

**Voice:** Concise and deterministic. Prefer `"3 of 5 files indexed"` over `"Everything is ready"` and `"No supporting passage found in workspace"` over `"I don't know."` Reserve vector scores, chunk IDs, and reranker telemetry for `{component.code-block}` disclosures in Search Explorer and Operator views.

---

## 3. Design Tokens (`GETDESIGN.MD` + RAG Extensions)

Components reference `GETDESIGN.MD` semantic tokens directly. Raw hex values are never hardcoded inside component stylesheets.

### Color Palette

| Semantic Role | `GETDESIGN.MD` Token | Value | Enterprise RAG Application |
| --- | --- | --- | --- |
| Page canvas | `{colors.canvas}` | `#f9f7f3` | Default backdrop across all authenticated and public views. |
| Inset group / rail | `{colors.surface-bone}` | `#f3f0e8` | Left navigation sidebar, quoted source passages, upload dropzones, and inset group bands. |
| Working card / input | `{colors.surface-card}` | `#ffffff` | Evidence cards, document rows, search inputs, dialogs, and source preview drawers. |
| Dark code / trace well | `{colors.surface-dark}` | `#202020` | `{component.code-block}` diagnostics, retrieval trace wells, featured evaluation tier, and `{component.button-dark}`. |
| Deep inset / footer | `{colors.surface-deep}` | `#000000` | `{component.code-tab}` strip inside code blocks and global `{component.footer}`. |
| Subtle divider | `{colors.hairline}` | `rgba(32,32,32,0.12)` | `1px` dividers between list rows, nav bar bottom border, and card edges. |
| Structural border | `{colors.hairline-strong}` | `#202020` | `{component.button-outline}` borders, focused inputs, and active structural separators. |
| Dark surface divider | `{colors.divider-dark}` | `rgba(252,252,252,0.16)` | Hairline separators inside `{colors.surface-dark}` and `{colors.surface-deep}` panels. |
| Primary ink | `{colors.ink}` | `#202020` | Headings, primary labels, document filenames, and high-contrast UI text. |
| Long-form prose | `{colors.body}` | `#3a3a3a` | Grounded assistant answers and multi-sentence excerpts (`16–18px`) to prevent ink fatigue. |
| Secondary text | `{colors.charcoal}` | `#575757` | Timestamps, page/slide anchors, secondary navigation, and table metadata. |
| Supporting / inactive | `{colors.mute}` | `#646464` | Inactive tab labels, helper captions, and empty-state secondary copy. |
| Tertiary / placeholder | `{colors.ash}` | `#8d8d8d` | Input placeholders and non-critical metadata. |
| Disabled foreground | `{colors.stone}` | `#bbbbbb` | Disabled control icons and inactive borders (accompanied by explanatory text). |
| Text on dark | `{colors.on-dark}` | `#fcfcfc` | Primary text inside `{colors.surface-dark}` wells, `{component.button-dark}`, and `{component.badge-status}`. |
| Muted text on dark | `{colors.on-dark-mute}` | `rgba(252,252,252,0.72)` | Secondary metadata and inactive `{component.code-tab}` labels on dark surfaces. |
| Brand accent / CTA | `{colors.primary}` | `#ea2804` | Single dominant `{component.button-primary}`, active `{component.code-tab}` underline, and inline `{colors.link}`. |
| Pressed CTA | `{colors.primary-deep}` | `#c01f00` | Active/pressed state for `{component.button-primary-pressed}`. |
| Text on primary | `{colors.on-primary}` | `#ffffff` | Label text on `{colors.primary}` surfaces. |
| Indexed / ready badge | `{colors.badge-success}` | `#2b9a66` | `{component.badge-status}` for `"Indexed"`, `"Ready"`, and healthy pipeline checks. |
| Inline link | `{colors.link}` | `#ea2804` | Underlined inline references and source jump links. |
| Focus ring | `{colors.ring-focus}` | `rgba(59,130,246,0.5)` | `3px` focus ring on interactive controls (`2px` solid fallback where high contrast is required). |

#### System Extensions (Closing `GETDESIGN.MD` Known Gaps)

`GETDESIGN.MD` documents public marketing surfaces and explicitly notes missing warning/error tokens and authenticated app states. The following extensions follow `GETDESIGN.MD` conventions and require validation before release:

| Extension Token | Light / Dark Value | Purpose |
| --- | --- | --- |
| `{colors.badge-warning}` / `{colors.surface-warning}` | `#8a5300` / `#fff1cc` | Partial extraction, OCR fallback, and RRF retrieval degradation (paired with warning icon + label). |
| `{colors.badge-error}` / `{colors.surface-error}` | `#b42318` / `#fce9e5` | Indexing failures, denied source access, and destructive confirmation actions. |
| `{colors.highlight-citation}` | `#fff0d4` (dark: `#3d3122`) | Background highlight linking an inline `{component.citation-chip}` to its passage inside `{component.source-drawer}`. |
| `{colors.app-dark-canvas}` | `#181817` | Optional user-selected Dark Theme base canvas (pairing with `{colors.surface-dark}` `#202020` cards and `{colors.on-dark}` `#fcfcfc` text). |

### Typography

Three strict font families with zero role overlap:

1. **`rb-freigeist-neue`** *(open-source fallback: **Bricolage Grotesque** or **Migra**)* — All display headers (`≥ 30px`). Clamp `lineHeight` to `1.0` and apply negative letter-spacing so multi-line headings lock into tight typographic blocks.
2. **`basier-square`** *(open-source fallback: **Geist** or **Inter**)* — All UI controls, navigation, answers, and metadata. Keep body weight strictly at `400` across `{typography.body-lg}` and `{typography.body-md}`; create emphasis through family shifts or `{typography.caption-tight}`, never weight `500`.
3. **`jetbrains-mono`** — Every code well, SQL/vector query, chunk ID, rank score, latency metric, model slug, and HTTP/error code. Never set technical identifiers in `basier-square`.

| `GETDESIGN.MD` Token | Size / Line Height | Weight | Tracking | Enterprise RAG Use |
| --- | --- | --- | --- | --- |
| `{typography.display-xxl}` | 128px / 1.0 | 700 | -3px | Unauthenticated entry `{component.hero-band}` only (clamps 128 → 96 → 64 → 48px). Never used on work screens. |
| `{typography.display-xl}` | 72px / 1.0 | 700 | -1.8px | Public/landing section openers and workspace onboarding splash. |
| `{typography.display-lg}` | 48px / 1.0 | 700 | -1px | Primary authenticated page titles (one per screen) and `{component.pricing-tier}` headers. |
| `{typography.display-md}` | 30px / 1.2 | 600 | -0.5px | Major section headings, dialog titles, and metric hero figures. |
| `{typography.heading-lg}` | 38.4px / 0.83 | 600 | -0.5px | Tightly stacked `basier-square` enterprise summary headers. |
| `{typography.heading-md}` | 24px / 1.33 | 600 | -0.35px | `{component.collection-tile}` titles, document detail headers, and drawer titles. |
| `{typography.heading-sm}` | 20px / 1.4 | 600 | -0.3px | List group headers, Search Explorer result group titles, and settings sections. |
| `{typography.subtitle}` | 18px / 1.56 | 600 | 0 | Lead descriptions under display headers and empty-state explanations. |
| `{typography.body-lg}` | 18px / 1.56 | 400 | 0 | Primary reading mode for long synthesized answers and full-passage previews. |
| `{typography.body-md}` | 16px / 1.5 | 400 | 0 | Default chat messages, source excerpts, and `{component.text-input}` copy. |
| `{typography.body-sm}` | 14px / 1.43 | 400 | 0 | Document row metadata, table cells, timestamps, and secondary navigation. |
| `{typography.button-md}` | 16px / 1.0 | 600 | 0 | `{component.button-primary}`, `{component.button-dark}`, `{component.button-outline}`, `{component.button-ghost}`. |
| `{typography.button-sm}` | 14px / 1.0 | 600 | 0 | `{component.nav-bar}` items, `{component.sub-nav-pill}`, and compact row actions. |
| `{typography.caption}` | 12px / 1.33 | 400 | 0 | `{component.badge-status}`, `{component.badge-tag}`, and `{component.footer}` disclosures. |
| `{typography.caption-tight}` | 14px / 1.43 | 600 | -0.35px | Emphatic table column headers, comparison row labels, and active filter summaries. |
| `{typography.code-md}` | 14px / 1.43 | 400 | 0 | `{component.code-block}` payloads, generated SQL, chunk JSON, and rerank traces. |
| `{typography.code-sm}` | 11px / 1.5 | 0 | `{component.code-tab}` labels, inline citation anchors (`[p.14]`), and chunk/doc IDs. |  |

Keep grounded answer prose constrained to `60–75` characters per line (`max-width: 760px`) and never truncate the sole visible filename or source location.

### Spacing, Shapes & Elevation

* **Spacing Scale (`GETDESIGN.MD`):**
* `{spacing.xxs}` `2px` · `{spacing.xs}` `4px` · `{spacing.sm}` `8px` · `{spacing.md}` `12px` · `{spacing.lg}` `16px` · `{spacing.xl}` `24px` · `{spacing.xxl}` `32px` · `{spacing.xxxl}` `48px` · `{spacing.section}` `96px` · `{spacing.band}` `160px`.
* Apply `{spacing.sm}` (`8px`) between label and control, `{spacing.lg}` (`16px`) inside `{component.model-card}` and dense document rows, `{spacing.xl}` (`24px`) inside `{component.collection-tile}` and `{component.code-block}`, and `{spacing.xxl}` (`32px`) inside `{component.pricing-tier}` and major layout gutters.


* **Border Radius Scale (`GETDESIGN.MD`):**
* `{rounded.none}` `0px`: Full-bleed `{component.hero-band}` and `{component.footer}`.
* `{rounded.xs}` `4px`: `{component.code-tab}` chips and inline tokens inside `{component.code-block}`.
* `{rounded.sm}` `6px`: Mid-radius inline callouts and small diagnostic chips.
* `{rounded.md}` `10px`: `{component.model-card}`, `{component.collection-tile}`, `{component.code-block}`, and document rows.
* `{rounded.lg}` `16px`: `{component.pricing-tier}`, `{component.source-drawer}`, dialogs, upload dropzones, and multiline prompt composers.
* `{rounded.full}` `9999px`: All buttons (`button-primary`, `button-dark`, `button-outline`, `button-ghost`, `button-icon`), single-line `{component.text-input}`, `{component.sub-nav-pill}`, `{component.badge-status}`, `{component.badge-tag}`, and `{component.contributor-avatar}`.


* **Elevation & Depth Levels (`GETDESIGN.MD`):**
* **Level 0 — flat:** Default `{colors.canvas}` (`#f9f7f3`) with no shadow and no border.
* **Level 1 — outline:** `1px solid {colors.hairline}` or `{colors.hairline-strong}` on `{colors.surface-card}` (`{component.model-card}`, `{component.pricing-tier}`).
* **Level 2 — bone inset:** Surface shift to `{colors.surface-bone}` (`#f3f0e8`) inside `{colors.canvas}` (sidebar shell, quoted evidence blocks, `{component.collection-tile}` bands).
* **Level 3 — dark inversion:** Surface swap to `{colors.surface-dark}` (`#202020`) against cream (`{component.code-block}`, `{component.pricing-tier-featured}`, retrieval trace panels).
* **Level 4 — soft drop:** `0 8px 24px rgba(32,32,32,0.08)` reserved exclusively for floating `{component.source-drawer}`, popovers, and modal overlays—never static cards on cream.


* **Motion:** `150–200ms` ease-out for drawer and disclosure transitions; zero ambient animations. Honor `prefers-reduced-motion` with instant state swaps.

---

## 4. Screen Inventory and Navigation

Top-level shell combines `{component.nav-bar}` (`60px` height on `{colors.canvas}` with `{colors.hairline}` bottom border) and a `240px` `{colors.surface-bone}` desktop sidebar listing **Chat**, **Documents**, **Search Explorer**, and **Analytics**, with **Workspace Settings**, **Operator Health & Evaluation**, and **Account** anchored at the bottom.

| Screen / Surface | Purpose | Entry |
| --- | --- | --- |
| Sign in / account access | Authenticate via verified methods and surface explicit session errors. | App entry / expired session. |
| Workspace selection & creation | Choose or create a private RAG workspace via `{component.collection-tile}` grid. | First login / workspace switcher. |
| Chat & grounded citations | Submit queries, stream grounded answers, and inspect inline citations in `{component.source-drawer}`. | Primary navigation. |
| Documents library | Upload, filter via `{component.sub-nav-pill}`, inspect, replace, retry, and delete corpus files. | Primary navigation. |
| Upload review & queue | Validate file types/sizes and track per-file parsing, chunking, and embedding stages. | Documents CTA. |
| Document detail & source preview | Inspect extraction warnings, chunk counts, version history, and page/slide/section anchors. | Document row or citation link. |
| Search Explorer | Run hybrid retrieval queries, inspect snippets, and expand `{component.code-block}` rank/RRF diagnostics. | Primary navigation. |
| Analytics | Track query volume, ingestion health, latency percentiles, and user feedback with table equivalents. | Primary navigation. |
| Workspace settings | Configure workspace identity and approved domain/chunking profile options with reindex warnings. | Sidebar footer menu. |
| Account / preferences | Manage account session and Light / Dark / System theme preference. | `{component.nav-bar}` account control. |
| Operator health & evaluation | Monitor service status, quotas, ingestion backlog, and versioned evaluation runs (`{component.pricing-tier}`). | Role-restricted operator nav. |
| Shared system surfaces | `{component.source-drawer}`, destructive confirmation dialogs, offline banner, and toast confirmations. | Contextual. |

---

## 5. Core User Flows

1. **Start a private workspace:** Sign in → select `{component.button-primary}` (“Create workspace”) → enter name in `{component.text-input}` → review private-scope notice → create → land on empty Documents screen with primary upload prompt.
2. **Upload and index corpus:** Documents → drop PDF/DOCX/PPTX/TXT/CSV into `{colors.surface-bone}` dropzone or trigger file picker → review per-file validation → click `{component.button-primary}` (“Upload files”) → track real per-file stage badges (`{component.badge-status}`) → when ready, select `{component.button-dark}` (“Ask about these documents”).
3. **Ask and verify with citations:** Chat → enter prompt in composer → submit via `{component.button-primary}` → monitor stage status and streaming `{typography.body-lg}` answer → click inline `{component.citation-chip}` → open `{component.source-drawer}` showing `{colors.highlight-citation}` passage inside a `{colors.surface-bone}` inset → close drawer and return focus to the invoking chip.
4. **Investigate hybrid retrieval:** Search Explorer → enter query in `{component.text-input}` and toggle `{component.sub-nav-pill}` filters → click `{component.button-dark}` (“Search”) → scan ranked `{component.model-card}` evidence rows → expand `{component.code-block}` diagnostic panel to inspect dense/sparse scores, reranker status, or RRF fallback.
5. **Replace or delete a document:** Documents → row `{component.button-icon}` menu → Replace or Delete → confirm in modal dialog. Replacement keeps the prior version searchable until the replacement reaches `Indexed` (`{colors.badge-success}`); deletion confirms immediate removal from search and prompts cleanup tracking.
6. **Review activity and evaluation runs:** Analytics → select date range via `{component.sub-nav-pill}` → inspect summary metrics, charts, and accessible data tables → Operator opens Evaluation view to compare baseline vs. candidate RAG runs using `{component.pricing-tier}` and `{component.pricing-tier-featured}` cards.
7. **Adapt domain profile:** Workspace settings → review current profile version → modify permitted chunking/metadata/prompt parameters → inspect reindex impact warning → save via `{component.button-dark}` and monitor background reindex status.

---

## 6. Per-Screen Layout (`GETDESIGN.MD` Component Mapping)

Authenticated screens use a `240px` `{colors.surface-bone}` sidebar, `{colors.canvas}` main region (`max-width: 1280px` body container; `760px` max reading measure for answers), and a single `{typography.display-lg}` (`48px`) or `{typography.display-md}` (`30px`) screen heading. Enforce **at most one `{component.button-primary}` (`#ea2804`) per viewport**; secondary primary-weight buttons use `{component.button-dark}` (`#202020`).

| Screen | Layout & Hierarchy (`GETDESIGN.MD` Surface & Type) | Primary Action & `GETDESIGN.MD` Components |
| --- | --- | --- |
| Sign in | Centered `{colors.surface-card}` panel (`{rounded.lg}`, Level 1 outline) on `{colors.canvas}`; title in `{typography.display-lg}`, concise purpose in `{typography.subtitle}`, inline errors in `{colors.badge-error}`. | **`{component.button-primary}`** (“Sign in”); `{component.text-input}` (`{rounded.full}`), `{component.button-dark}` (SSO/GitHub), inline alert. |
| Workspaces | `{typography.display-lg}` heading + private-access note on `{colors.canvas}`; `{colors.surface-bone}` band hosting `{component.collection-tile}` (`{rounded.md}`) workspace cards with last-activity metadata. | **`{component.button-primary}`** (“Create workspace”); `{component.collection-tile}`, modal dialog, `{component.text-input}`. |
| Chat | Top `{component.nav-bar}` (`60px`); main column (`760px` reading width) with `{typography.body-lg}` answers on `{colors.canvas}`/`{colors.surface-card}`; bottom multiline composer (`{rounded.lg}`) + right `{component.source-drawer}` (`{rounded.lg}`, Level 4). | **`{component.button-primary}`** (“Ask”); `{component.button-ghost}` (feedback/copy), `{component.badge-tag}` (citation chips), `{component.source-drawer}`, `{component.sub-nav-pill}` (starter prompts). |
| Documents | `{typography.display-lg}` heading + corpus quota summary; `{component.text-input}` search bar + `{component.sub-nav-pill}` status filters; `1px` `{colors.hairline}` list of `{component.model-card}` / document rows. | **`{component.button-primary}`** (“Upload documents”); `{component.text-input}`, `{component.sub-nav-pill}`, `{component.badge-status}`, `{component.badge-tag}`, `{component.button-icon}`. |
| Upload review | Modal dialog or mobile full-height sheet (`{colors.surface-card}`, `{rounded.lg}`); `{colors.surface-bone}` dropzone; per-file validation list with `{component.button-icon}` remove buttons. | **`{component.button-primary}`** (“Upload files”); `{colors.surface-bone}` dropzone, `{component.badge-status}`, `{component.button-outline}` (“Cancel”). |
| Document detail | `{component.button-ghost}` back link, filename in `{typography.heading-md}`, `{component.badge-status}` pill; 2-up split with `{colors.surface-bone}` excerpt preview and `{component.code-block}` chunk/metadata inspector. | **`{component.button-dark}`** (“Open original”); `{component.button-outline}` (“Replace”), `{component.code-block}`, `{component.code-tab}`, `{component.badge-status}`. |
| Search Explorer | `{typography.display-lg}` header; full-width `{component.text-input}` query bar + `{component.sub-nav-pill}` mode/type filters; ranked `{component.model-card}` evidence items with expandable `{component.code-block}` rank/RRF diagnostics. | **`{component.button-dark}`** (“Search”); `{component.text-input}`, `{component.sub-nav-pill}`, `{component.model-card}`, `{component.code-block}`, `{component.source-drawer}`. |
| Analytics | `{typography.display-lg}` header + `{component.sub-nav-pill}` date-range selector; 4-up `{component.collection-tile}` metric strip in `{colors.surface-bone}` band; charts paired with `{typography.body-sm}` accessible data tables. | **`{component.button-dark}`** (“Apply range”); `{component.sub-nav-pill}`, `{component.collection-tile}`, `{component.badge-status}`, semantic table. |
| Workspace settings | `{typography.display-lg}` header; grouped `{colors.surface-card}` (`{rounded.md}`) sections for Workspace Identity, Chunking/Domain Profile, and Reindex Impact with active profile badge. | **`{component.button-dark}`** (“Save changes”); `{component.text-input}`, `{component.sub-nav-pill}`, `{component.badge-tag}`, confirmation dialog. |
| Account / preferences | `{colors.surface-card}` (`{rounded.md}`) profile summary and Light / Dark / System `{component.sub-nav-pill}` selector; `{component.button-outline}` sign-out control. | **`{component.button-dark}`** (“Save preferences”); `{component.sub-nav-pill}`, `{component.button-outline}`. |
| Operator health & eval | Operator `{component.badge-tag}`; service status cards (`{colors.badge-success}`); 3-up `{component.pricing-tier}` & `{component.pricing-tier-featured}` (`{colors.surface-dark}`) grid comparing evaluation runs + `{component.code-block}` config diffs. | **`{component.button-dark}`** (“Compare runs”); `{component.pricing-tier}`, `{component.pricing-tier-featured}`, `{component.code-block}`, `{component.button-outline}` (“Export JSON”). |
| Source preview drawer | `{colors.surface-card}` (`{rounded.lg}`, `360–440px` desktop, Level 4 soft drop); filename in `{typography.heading-md}`, `{typography.code-sm}` anchor, `{colors.surface-bone}` quoted passage with `{colors.highlight-citation}` span. | **`{component.button-outline}`** (“Open original”); `{component.button-icon}` (close/prev/next page), `{component.badge-tag}`. |

---

## 7. Reusable Component Library (`GETDESIGN.MD` Primitives & RAG Adaptations)

All interactive controls implement default, hover, `{colors.ring-focus}` focus, active/pressed, disabled, and busy states. Disabled buttons never stand alone without explanatory helper text in `{colors.mute}`.

| Component Token | Base `GETDESIGN.MD` Spec | Enterprise RAG Behavior & Variants |
| --- | --- | --- |
| `{component.nav-bar}` & Sidebar Shell | `60px` top bar on `{colors.canvas}` with `1px` `{colors.hairline}` border (`{typography.button-sm}`), paired with `240px` `{colors.surface-bone}` sidebar. | Displays brand wordmark, active workspace context, primary route links (`aria-current="page"`), and account menu; collapses to hamburger + drawer below `1024px`. |
| `{component.button-primary}` / `-pressed` | `{colors.primary}` (`#ea2804`), `{colors.on-primary}` (`#ffffff`), `{typography.button-md}`, `12px 24px` padding, `{rounded.full}`, `44px` height; pressed swaps to `{colors.primary-deep}` (`#c01f00`). | Reserved strictly for the single primary CTA per viewport (“Ask”, “Upload files”, “Create workspace”). Busy state locks width and shows subtle spinner. |
| `{component.button-dark}` | `{colors.surface-dark}` (`#202020`), `{colors.on-dark}` (`#fcfcfc`), `{typography.button-md}`, `{rounded.full}`, `44px` height. | Primary-weight action on `{colors.canvas}` when `{component.button-primary}` is already present or too loud (“Search”, “Save changes”, “Open original”). |
| `{component.button-outline}` | `{colors.surface-card}` (`#ffffff`), `{colors.ink}` (`#202020`), `1px solid {colors.hairline-strong}`, `{typography.button-md}`, `{rounded.full}`, `44px` height. | Secondary actions (“Replace document”, “Export evaluation”, “Cancel”). |
| `{component.button-ghost}` | `{colors.canvas}`, `{colors.ink}`, borderless, `{typography.button-md}`, `{rounded.full}`, `8px 16px` padding. | Low-friction inline controls inside answers and cards (“Copy answer”, “Thumbs up/down”, “Show retrieval trace”). |
| `{component.button-icon}` | `{colors.surface-card}`, `{colors.ink}`, `1px solid {colors.hairline}`, `{rounded.full}`, `36×36px` desktop (`44×44px` mobile touch target). | Drawer close (`×`), citation/page pagination arrows, copy-code button, and row overflow menu (`⋮`). |
| `{component.text-input}` & Composer | `{colors.surface-card}`, `{colors.ink}`, `{typography.body-md}`, `1px solid {colors.hairline}`, `{rounded.full}`, `12px 20px`, `44px` height, `3px` `{colors.ring-focus}` ring. | Used verbatim for Search Explorer, document filter, and login fields. Multiline Chat composer adapts to `{rounded.lg}` (`16px`) with `1px solid {colors.hairline-strong}` on focus to preserve reading space. |
| `{component.sub-nav-pill}` | `{rounded.full}`, `{typography.button-sm}`, `36px` desktop / `40px` mobile height; active state in `{colors.surface-dark}` + `{colors.on-dark}`. | Workspace switcher pills, document status filters (`All`, `Indexed`, `Processing`, `Failed`), Search mode toggles (`Hybrid`, `Vector`, `Keyword`), and date ranges. |
| `{component.model-card}` (Evidence / Doc Card) | `{colors.surface-card}`, `{colors.ink}`, `1px solid {colors.hairline}`, `{rounded.md}` (`10px`), `{spacing.lg}` (`16px`) padding. | Renders Search Explorer hits and Document items: title in `{typography.heading-sm}`, excerpt in `{colors.body}`, `{component.badge-status}` bottom-left, and `{component.badge-tag}` format/page pills. |
| `{component.collection-tile}` | `{colors.canvas}` tile nested inside `{colors.surface-bone}` (`Level 2`) band, `{typography.heading-md}`, `{rounded.md}`, `{spacing.xl}` (`24px`) padding. | Used for Workspace selector cards, Domain Profile cards, and Analytics summary metric tiles. |
| `{component.code-block}` & `{component.code-tab}` | `{colors.surface-dark}` container (`{rounded.md}`, `{spacing.xl}` padding, `{typography.code-md}`); `{colors.surface-deep}` tab strip (`{rounded.xs}`, `{typography.code-sm}`, `2px solid {colors.primary}` active underline). | Displays retrieval pipeline diagnostics, reranker/RRF fallback logs, generated SQL queries, raw chunk JSON, and cURL/Python API snippets. |
| `{component.pricing-tier}` & `-featured` | `{rounded.lg}` (`16px`), `{spacing.xxl}` (`32px`) padding; standard in `{colors.surface-card}`, featured in `{colors.surface-dark}` (`Level 3` inversion). | Re-purposed in Operator Evaluation & Workspace Settings to compare evaluation runs or chunking presets side by side, highlighting the active/recommended baseline in dark inversion. |
| `{component.badge-status}` & `{component.badge-tag}` | `{rounded.full}`, `{typography.caption}`, `4px 10px` padding. Status uses `{colors.badge-success}` + `{colors.on-dark}`; tag uses `{colors.canvas}` + `1px solid {colors.hairline}`. | `{component.badge-status}` marks `Indexed` / `Healthy` (with `{colors.badge-warning}` and `{colors.badge-error}` extensions for `Partial` / `Failed`). `{component.badge-tag}` renders file types (`PDF`, `DOCX`) and inline citation chips (`[report.pdf · p.4]`). |
| `{component.hero-band}` & `{component.footer}` | `{rounded.none}` (`0px`). Hero uses `{colors.hero-warm}` mesh + `{typography.display-xxl}`; Footer uses `{colors.surface-deep}` + `{colors.on-dark}`. | `{component.hero-band}` is restricted strictly to unauthenticated landing pages. `{component.footer}` anchors global documentation, schema version, and privacy links. |
| `{component.source-drawer}` *(RAG Extension)* | `{colors.surface-card}`, `{rounded.lg}` (`16px`), `Level 4` soft drop (`0 8px 24px rgba(32,32,32,0.08)`), `360–440px` desktop width. | Displays verified source excerpt inside a `{colors.surface-bone}` inset with `{colors.highlight-citation}` passage highlight, `{typography.code-sm}` anchor, and `{component.button-outline}` (“Open original”). |

---

## 8. Screen States

**Offline** means the browser or backend API is unreachable. Never imply cached availability or background sync unless explicitly implemented; retain unsent drafts in memory and disable network mutations.

| Screen | Empty | Loading | Error / Degraded | Success | Offline |
| --- | --- | --- | --- | --- | --- |
| Sign in | Blank `{component.text-input}` fields with persistent labels. | `{component.button-primary}` busy; inputs locked. | Inline `{colors.badge-error}` banner with non-enumerating guidance. | Redirect to active workspace. | Offline banner; disable submit while preserving non-secret input. |
| Workspaces | `{typography.subtitle}` private-scope guide + `{component.button-primary}`. | `{colors.surface-bone}` `{component.collection-tile}` skeletons. | Error callout with `{component.button-dark}` retry. | Workspace opens and scopes sidebar/history. | Stale-list warning banner; disable creation. |
| Chat | Starter `{component.sub-nav-pill}` prompts clearly labeled as examples. | Stage indicator (`Retrieving…`, `Reranking…`) + streaming `{typography.body-lg}`. | Insufficient-evidence notice, unavailable source tag, or labeled RRF fallback in `{component.code-block}`. | Grounded answer with `{component.badge-tag}` citations and `{component.button-ghost}` feedback. | Preserve draft in composer memory; disable `{component.button-primary}` send. |
| Documents | Supported format summary + `{colors.surface-bone}` dropzone. | List skeleton + real per-file stage `{component.badge-status}`. | Failed/partial rows with `{colors.badge-error}` / `{colors.badge-warning}` and retry `{component.button-icon}`. | `{colors.badge-success}` `Indexed` badge; file searchable. | Mark list potentially stale; disable upload and delete. |
| Upload review | File selection prompt inside `{colors.surface-bone}` dropzone. | Per-file transfer bar + processing stage badge. | Per-file validation or upload failure with selective retry. | Files accepted into ingestion pipeline. | Flag interrupted upload; allow retry upon reconnect. |
| Document detail | Explains why binary preview is unavailable while retaining metadata. | Preview skeleton + stage progress. | Denied, deleted, or partial extraction warning banner. | Authorized excerpt + accurate `{typography.code-sm}` page/slide anchor. | Disable preview fetch; avoid showing stale content as live. |
| Search Explorer | Query prompt + `{component.sub-nav-pill}` filter explanation. | Progress indicator with query preserved in `{component.text-input}`. | Zero-hit guidance, provider error, or explicit RRF fallback banner. | Ranked `{component.model-card}` results + expandable `{component.code-block}` scores. | Keep query in `{component.text-input}`; disable search CTA. |
| Analytics | Period-scoped zero-data notice in `{typography.subtitle}`. | `{component.collection-tile}` metric skeletons. | Partial metric warning with data-freshness timestamp and retry. | Metric tiles, charts, and accessible data tables. | Label displayed figures stale; suppress live polling claims. |
| Settings / Account | Current defaults with `{colors.mute}` helper text. | Field skeleton / busy `{component.button-dark}`. | Inline validation or reindex-required warning banner. | Saved confirmation + real reindex job status. | Retain unsaved form edits in memory; disable save. |
| Operator health | No evaluation runs notice + `{component.button-dark}` trigger. | Service status skeletons. | Name failing service, last heartbeat, and degraded capability. | `{colors.badge-success}` service status + `{component.pricing-tier}` eval comparison. | Mark telemetry stale and connection lost; never show healthy. |

---

## 9. Responsive Behavior (`GETDESIGN.MD` Breakpoint Ladder)

| Breakpoint | Width | Layout & Navigation | Component & Touch-Target Adaptation |
| --- | --- | --- | --- |
| **Desktop XL** | `≥ 1440px` | `240px` `{colors.surface-bone}` sidebar + `1280px` max body container; full-bleed bands at `1440px`. | Chat answer (`760px`) and `{component.source-drawer}` (`400px`) sit side by side without compressing prose. |
| **Desktop** | `1280–1439px` | `240px` sidebar + fluid body container with `{spacing.xl}` (`24px`) side padding. | `4`-column `{component.collection-tile}` / metric grid; Search Explorer shows list + inline `{component.code-block}` traces. |
| **Tablet Large** | `1024–1279px` | Expanded or compact rail; `3`-column tile grid; `2`-up detail and evaluation splits. | `{component.source-drawer}` opens as `360px` overlay (`Level 4` soft drop) when width would shrink answer `< 480px`. |
| **Tablet** | `768–1023px` | `{component.nav-bar}` collapses sidebar into hamburger drawer; `2`-column tile grid; `2`-up splits stack vertically. | `{component.pricing-tier}` evaluation grid stacks vertically with `{component.pricing-tier-featured}` centered. `{component.code-block}` wraps long lines with continuation markers. |
| **Mobile Large** | `426–767px` | Single-column layout (`{spacing.lg}` `16px` gutters); `{component.nav-bar}` (`60px`) keeps wordmark left and primary action right. | `{component.sub-nav-pill}` converts to horizontal scroll-rail (`40px` height). `{component.button-icon}` expands from `36px` to `44×44px`. `{component.source-drawer}` opens as full-height sheet. |
| **Mobile** | `≤ 425px` | All grids `1`-up; section padding collapses from `{spacing.section}` (`96px`) to `64px`; any landing `{typography.display-xxl}` clamps to `48px`. | Composer stays pinned above virtual keyboard; document cards stack metadata vertically; zero horizontal page overflow at `320px`. |

At `200%` browser zoom, reflow into the `< 768px` single-column pattern while preserving reading order and keyboard focus sequence.

---

## 10. Accessibility and Verification

* **WCAG 2.2 AA Contrast & Token Audits:**
* Verify all token pairs in Light and Dark themes (`≥ 4.5:1` normal text, `≥ 3:1` large text and meaningful UI boundaries).
* **Known `GETDESIGN.MD` Contrast Rule:** `{colors.on-primary}` (`#ffffff`) on `{colors.primary}` (`#ea2804`) measures `4.37:1`—valid for bold/semibold UI labels `≥ 14px` (`{typography.button-md}` `16px/600` passes WCAG AA large-text threshold) and `{typography.display-xxl}`/`xl` headers, but **never** use `#ea2804` behind normal `< 18.66px` body text or small `12px` badges. Use `{component.button-dark}` (`#fcfcfc` on `#202020`, `16.4:1`) for compact high-contrast controls.
* Validate `{colors.ring-focus}` (`rgba(59,130,246,0.5)`) over both `{colors.canvas}` (`#f9f7f3`) and `{colors.surface-dark}` (`#202020`), adding a `2px` high-contrast outline fallback where needed.


* **Landmarks, Keyboard & Focus Management:**
* Semantic order: Skip link → `{component.nav-bar}` / Sidebar → `<main>` (`{typography.display-lg}` heading) → screen controls → content → `{component.source-drawer}`.
* Trap focus inside modal dialogs and `{component.source-drawer}`, close on `Escape`, and restore focus to the invoking `{component.citation-chip}` or `{component.button-icon}`.
* Support `Enter` to submit and `Shift+Enter` for newlines in the Chat composer; never make drag-and-drop the sole upload path.


* **Screen-Reader Announcements & Non-Color Cues:**
* Use a polite `aria-live` region for ingestion stage transitions and completed answers; never announce individual streamed tokens.
* Pair `{colors.badge-success}`, `{colors.badge-warning}`, and `{colors.badge-error}` with explicit status icons and text labels; provide semantic HTML tables beneath all Analytics charts.


* **Design System Linting & Testing:**
* Run `npx @google/design.md lint DESIGN.md` whenever tokens or component variants change to eliminate orphaned tokens.
* Execute keyboard-only, screen-reader, `200%` zoom, and `prefers-reduced-motion` verification across Sign in, Upload, Ask, Citation Drawer, Search Explorer, and Delete flows before release.



---

## Decisions to Validate Before Implementation

1. **Resolve `GETDESIGN.MD` Known Gaps:** Confirm the exact hex values for `{colors.badge-warning}`, `{colors.badge-error}`, `{colors.highlight-citation}`, and full-app dark-mode surfaces, as `GETDESIGN.MD` only extracts public light-mode marketing surfaces.
2. **Font Licensing & Fallbacks:** Confirm commercial licensing for `rb-freigeist-neue` and `basier-square`, or lock in local WOFF2 bundling for open-source substitutes (`Bricolage Grotesque` + `Geist` + `JetBrains Mono`) with explicit `-3%` display tracking and `lineHeight: 1.0` clamping.
3. **One-Stamp `{colors.primary}` Enforcement:** Audit every screen layout during wireframing to confirm `{colors.primary}` (`#ea2804`) appears at most once per viewport and that secondary primary actions cleanly step down to `{component.button-dark}`.
4. **Domain Profile & Operator Permissions:** Confirm which chunking, reranking, and prompt-profile parameters users can safely modify in Workspace Settings without triggering unintended corpus-wide reindexing.
