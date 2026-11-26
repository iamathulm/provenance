import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const css = readFileSync(join(__dirname, "tokens.css"), "utf8");

const REQUIRED_TOKENS = [
  "--color-canvas",
  "--color-surface-bone",
  "--color-surface-card",
  "--color-surface-dark",
  "--color-surface-deep",
  "--color-hairline",
  "--color-hairline-strong",
  "--color-divider-dark",
  "--color-ink",
  "--color-body",
  "--color-charcoal",
  "--color-mute",
  "--color-ash",
  "--color-stone",
  "--color-on-dark",
  "--color-on-dark-mute",
  "--color-primary",
  "--color-primary-deep",
  "--color-on-primary",
  "--color-badge-success",
  "--color-badge-warning",
  "--color-surface-warning",
  "--color-badge-error",
  "--color-surface-error",
  "--color-highlight-citation",
  "--color-ring-focus",
  "--radius-xs",
  "--radius-sm",
  "--radius-md",
  "--radius-lg",
  "--radius-full",
  "--spacing-xxs",
  "--spacing-xs",
  "--spacing-sm",
  "--spacing-md",
  "--spacing-lg",
  "--spacing-xl",
  "--spacing-xxl",
  "--spacing-xxxl",
  "--spacing-section",
  "--spacing-band",
];

describe("design tokens", () => {
  it.each(REQUIRED_TOKENS)("declares %s", (token) => {
    expect(css).toMatch(new RegExp(`${token}\s*:`));
  });

  it("uses the exact brand values from the design brief", () => {
    expect(css).toMatch(/--color-primary:\s*#ea2804;/);
    expect(css).toMatch(/--color-canvas:\s*#f9f7f3;/);
  });
});
