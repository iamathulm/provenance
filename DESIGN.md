---
version: alpha
name: Provenance
description: Calm research-desk design system for an evidence-first RAG product — warm cream paper, warm charcoal ink, dark printed code wells, and a single hot-orange stamp per viewport.
colors:
  canvas: "#F9F7F3"
  surface-bone: "#F3F0E8"
  surface-card: "#FFFFFF"
  surface-dark: "#202020"
  surface-deep: "#000000"
  hairline: "#2020201F"
  hairline-strong: "#202020"
  divider-dark: "#FCFCFC29"
  ink: "#202020"
  body: "#3A3A3A"
  charcoal: "#575757"
  mute: "#646464"
  ash: "#8D8D8D"
  stone: "#BBBBBB"
  on-dark: "#FCFCFC"
  on-dark-mute: "#FCFCFCB8"
  brand: "#EA2804"
  primary: "#C01F00"
  primary-pressed: "#A31A00"
  on-primary: "#FFFFFF"
  link: "#C01F00"
  badge-success: "#1F6E4A"
  surface-success: "#E3F4EB"
  badge-warning: "#8A5300"
  surface-warning: "#FFF1CC"
  badge-error: "#B42318"
  surface-error: "#FCE9E5"
  highlight-citation: "#FFF0D4"
  ring-focus: "#3B82F680"
typography:
  display-xxl:
    fontFamily: Bricolage Grotesque
    fontSize: 128px
    fontWeight: 700
    lineHeight: 1
    letterSpacing: -3px
  display-xl:
    fontFamily: Bricolage Grotesque
    fontSize: 72px
    fontWeight: 700
    lineHeight: 1
    letterSpacing: -1.8px
  display-lg:
    fontFamily: Bricolage Grotesque
    fontSize: 48px
    fontWeight: 700
    lineHeight: 1
    letterSpacing: -1px
  display-md:
    fontFamily: Bricolage Grotesque
    fontSize: 30px
    fontWeight: 600
    lineHeight: 1.2
    letterSpacing: -0.5px
  heading-md:
    fontFamily: Geist
    fontSize: 24px
    fontWeight: 600
    lineHeight: 1.33
    letterSpacing: -0.35px
  heading-sm:
    fontFamily: Geist
    fontSize: 20px
    fontWeight: 600
    lineHeight: 1.4
    letterSpacing: -0.3px
  subtitle:
    fontFamily: Geist
    fontSize: 18px
    fontWeight: 600
    lineHeight: 1.56
  body-lg:
    fontFamily: Geist
    fontSize: 18px
    fontWeight: 400
    lineHeight: 1.56
  body-md:
    fontFamily: Geist
    fontSize: 16px
    fontWeight: 400
    lineHeight: 1.5
  body-sm:
    fontFamily: Geist
    fontSize: 14px
    fontWeight: 400
    lineHeight: 1.43
  button-md:
    fontFamily: Geist
    fontSize: 16px
    fontWeight: 600
    lineHeight: 1
  button-sm:
    fontFamily: Geist
    fontSize: 14px
    fontWeight: 600
    lineHeight: 1
  caption:
    fontFamily: Geist
    fontSize: 12px
    fontWeight: 400
    lineHeight: 1.33
  caption-tight:
    fontFamily: Geist
    fontSize: 14px
    fontWeight: 600
    lineHeight: 1.43
    letterSpacing: -0.35px
  code-md:
    fontFamily: JetBrains Mono
    fontSize: 14px
    fontWeight: 400
    lineHeight: 1.43
  code-sm:
    fontFamily: JetBrains Mono
    fontSize: 11px
    fontWeight: 400
    lineHeight: 1.5
rounded:
  none: 0px
  xs: 4px
  sm: 6px
  md: 10px
  lg: 16px
  full: 9999px
spacing:
  xxs: 2px
  xs: 4px
  sm: 8px
  md: 12px
  lg: 16px
  xl: 24px
  xxl: 32px
  xxxl: 48px
  section: 96px
  band: 160px
components:
  button-primary:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.on-primary}"
    typography: "{typography.button-md}"
    rounded: "{rounded.full}"
    padding: 12px 24px
    height: 44px
  button-primary-pressed:
    backgroundColor: "{colors.primary-pressed}"
    textColor: "{colors.on-primary}"
  button-dark:
    backgroundColor: "{colors.surface-dark}"
    textColor: "{colors.on-dark}"
    typography: "{typography.button-md}"
    rounded: "{rounded.full}"
    height: 44px
  button-outline:
    backgroundColor: "{colors.surface-card}"
    textColor: "{colors.ink}"
    typography: "{typography.button-md}"
    rounded: "{rounded.full}"
    height: 44px
  button-ghost:
    backgroundColor: "{colors.canvas}"
    textColor: "{colors.ink}"
    typography: "{typography.button-md}"
    rounded: "{rounded.full}"
    padding: 8px 16px
  button-icon:
    backgroundColor: "{colors.surface-card}"
    textColor: "{colors.ink}"
    rounded: "{rounded.full}"
    size: 36px
  text-input:
    backgroundColor: "{colors.surface-card}"
    textColor: "{colors.ink}"
    typography: "{typography.body-md}"
    rounded: "{rounded.full}"
    padding: 12px 20px
    height: 44px
  sub-nav-pill:
    backgroundColor: "{colors.canvas}"
    textColor: "{colors.ink}"
    typography: "{typography.button-sm}"
    rounded: "{rounded.full}"
    height: 36px
  sub-nav-pill-active:
    backgroundColor: "{colors.surface-dark}"
    textColor: "{colors.on-dark}"
  model-card:
    backgroundColor: "{colors.surface-card}"
    textColor: "{colors.ink}"
    typography: "{typography.body-md}"
    rounded: "{rounded.md}"
    padding: 16px
  collection-tile:
    backgroundColor: "{colors.canvas}"
    textColor: "{colors.ink}"
    typography: "{typography.heading-md}"
    rounded: "{rounded.md}"
    padding: 24px
  pricing-tier:
    backgroundColor: "{colors.surface-card}"
    textColor: "{colors.ink}"
    typography: "{typography.body-md}"
    rounded: "{rounded.lg}"
    padding: 32px
  pricing-tier-featured:
    backgroundColor: "{colors.surface-dark}"
    textColor: "{colors.on-dark}"
    typography: "{typography.body-md}"
    rounded: "{rounded.lg}"
    padding: 32px
  code-block:
    backgroundColor: "{colors.surface-dark}"
    textColor: "{colors.on-dark}"
    typography: "{typography.code-md}"
    rounded: "{rounded.md}"
    padding: 24px
  code-tab:
    backgroundColor: "{colors.surface-deep}"
    textColor: "{colors.on-dark-mute}"
    typography: "{typography.code-sm}"
    rounded: "{rounded.xs}"
    padding: 6px 12px
  badge-status:
    backgroundColor: "{colors.surface-success}"
    textColor: "{colors.badge-success}"
    typography: "{typography.caption}"
    rounded: "{rounded.full}"
    padding: 4px 10px
  badge-status-warning:
    backgroundColor: "{colors.surface-warning}"
    textColor: "{colors.badge-warning}"
    typography: "{typography.caption}"
    rounded: "{rounded.full}"
    padding: 4px 10px
  badge-status-error:
    backgroundColor: "{colors.surface-error}"
    textColor: "{colors.badge-error}"
    typography: "{typography.caption}"
    rounded: "{rounded.full}"
    padding: 4px 10px
  badge-tag:
    backgroundColor: "{colors.canvas}"
    textColor: "{colors.ink}"
    typography: "{typography.caption}"
    rounded: "{rounded.full}"
    padding: 4px 10px
  source-drawer:
    backgroundColor: "{colors.surface-card}"
    textColor: "{colors.ink}"
    rounded: "{rounded.lg}"
    width: 400px
  citation-highlight:
    backgroundColor: "{colors.highlight-citation}"
    textColor: "{colors.body}"
  nav-bar:
    backgroundColor: "{colors.canvas}"
    textColor: "{colors.ink}"
    typography: "{typography.button-sm}"
    height: 60px
  sidebar:
    backgroundColor: "{colors.surface-bone}"
    textColor: "{colors.ink}"
    width: 240px
  footer:
    backgroundColor: "{colors.surface-deep}"
    textColor: "{colors.on-dark}"
    typography: "{typography.body-sm}"
    rounded: "{rounded.none}"
    padding: 64px 32px
  hero-band:
    backgroundColor: "{colors.brand}"
    textColor: "{colors.on-primary}"
    typography: "{typography.display-xxl}"
    rounded: "{rounded.none}"
  code-tab-active-underline:
    backgroundColor: "{colors.brand}"
  inline-link:
    textColor: "{colors.link}"
  metadata-text:
    textColor: "{colors.charcoal}"
    typography: "{typography.body-sm}"
  helper-text:
    textColor: "{colors.mute}"
    typography: "{typography.body-sm}"
  input-placeholder:
    textColor: "{colors.mute}"
  decorative-icon:
    textColor: "{colors.ash}"
  disabled-control:
    backgroundColor: "{colors.surface-card}"
    textColor: "{colors.stone}"
  focus-ring:
    backgroundColor: "{colors.ring-focus}"
  divider:
    backgroundColor: "{colors.hairline}"
  divider-strong:
    backgroundColor: "{colors.hairline-strong}"
  divider-on-dark:
    backgroundColor: "{colors.divider-dark}"
---

## Overview

Provenance is a calm research desk with editorial precision. Answers and their evidence are the
visual focus: warm cream paper (`{colors.canvas}`) instead of white, warm charcoal ink
(`{colors.ink}`), hairline rules instead of shadows, dark printed wells for anything technical
(SQL, chunk IDs, scores, traces), and a single hot-orange stamp (`{colors.brand}`) per viewport.

Principles:

1. **Evidence beside the answer.** Every substantive answer exposes its excerpt, document title and
   page/slide/section/row anchor in one action. Unsupported answers say so explicitly.
2. **Legible progress and limits.** Real ingestion stages, retrieval modes (hybrid, reranked, RRF
   fallback) and actionable errors in plain language. Never imply a document is searchable early.
3. **Reading over decoration.** Strict type lanes, pill controls, rectangular reading cards.

Voice is concise and deterministic: "3 of 5 files indexed", "No supporting passage found in
workspace". No glowing AI motifs, robots, gradients on work screens, or invented confidence numbers.

## Colors

- **Canvas (`{colors.canvas}`)** is the page background everywhere. Pure white
  (`{colors.surface-card}`) appears only on cards, inputs, dialogs and the source drawer.
- **Surface Bone (`{colors.surface-bone}`)** is the inset step: sidebar, quoted evidence, dropzones.
- **Surface Dark / Deep** host code wells, retrieval diagnostics, featured evaluation tiers and the footer.
- **Ink, Body, Charcoal, Mute, Ash, Stone** form the text ladder; long answers use `{colors.body}`.
- **Brand (`{colors.brand}`)** is the stamp color: the landing hero band and non-text accents (active tab underline). The one primary CTA per viewport and inline links use the accessible `{colors.primary}`.
  Never on body text, small badges or large surfaces.
- **Status** colors (success, warning, error) are always paired with an icon and a text label.
- **Highlight Citation (`{colors.highlight-citation}`)** links a citation chip to its passage.
- **Focus ring (`{colors.ring-focus}`)**, 3px, with a 2px solid fallback where contrast requires.

**Accessibility adjustments to the design brief (WCAG 2.2 AA, PRD NFR-06):**

- White on `{colors.brand}` is 4.37:1 and 16px semibold is not "large text", so the
  `button-primary` fill uses `{colors.primary}` (6.11:1; pressed `{colors.primary-pressed}`
  7.76:1). Bright `{colors.brand}` remains for the landing hero band and non-text accents
  (active tab underline), which only need 3:1.
- Inline links use `{colors.link}` = `{colors.primary}` (5.71:1 on canvas; bright orange is 4.09:1).
- Success badges follow the warning/error pattern — `{colors.surface-success}` with
  `{colors.badge-success}` text (5.43:1) — instead of white on mid-green (3.46:1).
- Placeholders use `{colors.mute}`; `{colors.ash}` is reserved for non-text decoration.
- Expected linter warnings: `hero-band` (white on bright orange, 4.37:1) carries only 48–128px
  display text, which needs 3:1; `disabled-control` is exempt under WCAG 1.4.3 (inactive UI) and
  is always accompanied by helper text in `{colors.mute}`.

## Typography

Three families, three jobs, no overlap:

- **Bricolage Grotesque** — all display sizes (≥ 30px), `lineHeight` 1.0 with negative tracking.
- **Geist** — UI, navigation, answers, metadata. Body weight stays 400; emphasis comes from a
  family change or `{typography.caption-tight}`, never weight 500.
- **JetBrains Mono** — every code well, SQL, chunk ID, score, latency, model slug and error code.

Answer prose is constrained to 60–75 characters per line (max 760px). Never truncate the only
visible filename or source location.

## Layout

4px base unit. Authenticated screens: 60px nav bar, 240px bone sidebar, 1280px max body container,
760px reading measure for answers, one display-lg heading per screen. Cards pad 16px, tiles and
code wells 24px, evaluation tiers 32px. Breakpoints: ≥1440, 1280–1439, 1024–1279, 768–1023,
426–767, ≤425. No horizontal page scroll at 320px; reflow to single column at 200% zoom.

## Elevation & Depth

Color-blocking, not shadows:

- Level 0 flat canvas · Level 1 hairline outline on card · Level 2 bone inset · Level 3 dark inversion.
- Level 4 soft drop (`0 8px 24px` ink at 8%) only for the floating source drawer, popovers and modals.

Motion is 150–200ms ease-out for drawers and disclosures; no ambient animation; honor
`prefers-reduced-motion` with instant swaps.

## Shapes

Every interactive control — buttons, single-line inputs, pills, badges, avatars — is
`{rounded.full}`. Content containers step to `{rounded.md}` (cards, tiles, code wells, document rows)
or `{rounded.lg}` (drawer, dialogs, dropzones, multiline composer, evaluation tiers). Square corners
only on full-bleed bands (landing hero, footer).

## Components

- **Buttons:** `button-primary` (one per viewport), `button-dark` (primary-weight alternative),
  `button-outline` (secondary), `button-ghost` (inline: copy, feedback, show trace), `button-icon`
  (36px, 44px on touch). All implement default, hover, focus, pressed, disabled (with helper text)
  and busy states.
- **Inputs:** pill `text-input`; the multiline chat composer uses `{rounded.lg}` and a strong
  hairline on focus. Enter submits, Shift+Enter adds a newline.
- **Cards:** `model-card` for evidence hits and document rows; `collection-tile` for workspaces,
  domain profiles and metric tiles; `pricing-tier` / `pricing-tier-featured` to compare evaluation
  runs and chunking presets side by side.
- **Code:** `code-block` with `code-tab` strip (active tab gets a 2px brand underline) for SQL,
  chunk JSON, rerank and RRF diagnostics, and API snippets.
- **Status:** `badge-status` (success / warning / error variants, always icon + label) for job
  stages; `badge-tag` for formats and inline citation chips like `[report.pdf · p.4]`.
- **Source drawer:** 360–440px floating card (level 4) with filename, mono anchor, and the quoted
  passage in a bone inset with `{colors.highlight-citation}`. Traps focus, closes on Escape, and
  returns focus to the invoking chip.

## Do's and Don'ts

Do:

- Use `{colors.canvas}` as the default background and keep white for cards and inputs.
- Keep orange (the `{colors.brand}` accent or a `{colors.primary}` fill) to one element per viewport; demote others to `button-dark`.
- Put every technical identifier in JetBrains Mono inside a dark well or mono chip.
- Pair every status color with an icon and text; give charts an accessible data table.

Don't:

- Use pure white page backgrounds, gradients on work screens, or drop shadows on cream.
- Round content cards fully, or loosen display line-height past 1.0.
- Bump body text to weight 500, or set code in Geist.
- Show invented confidence percentages or announce individual streamed tokens to screen readers.
