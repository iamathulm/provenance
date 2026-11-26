import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const tokensCss = readFileSync(join(__dirname, "tokens.css"), "utf8");
const globalsCss = readFileSync(join(__dirname, "..", "app", "globals.css"), "utf8");

const declares = (css: string, token: string) => new RegExp(String.raw`${token}\s*:`).test(css);

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
  "--color-brand",
  "--color-primary",
  "--color-primary-pressed",
  "--color-on-primary",
  "--color-link",
  "--color-badge-success",
  "--color-surface-success",
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

const FONT_TOKENS = ["--font-display", "--font-sans", "--font-mono"];

describe("design tokens", () => {
  it.each(REQUIRED_TOKENS)("declares %s", (token) => {
    expect(declares(tokensCss, token)).toBe(true);
  });

  it.each(FONT_TOKENS)("maps font role %s in globals.css", (token) => {
    expect(declares(globalsCss, token)).toBe(true);
  });

  it("matches declarations with whitespace before the colon", () => {
    expect(declares("--color-ink : #202020;", "--color-ink")).toBe(true);
  });

  it("uses the exact surface and brand values from the design brief", () => {
    expect(tokensCss).toMatch(/--color-canvas:\s*#f9f7f3;/);
    expect(tokensCss).toMatch(/--color-brand:\s*#ea2804;/);
  });

  it("uses WCAG AA-compliant values for text-bearing orange and status colors", () => {
    expect(tokensCss).toMatch(/--color-primary:\s*#c01f00;/);
    expect(tokensCss).toMatch(/--color-link:\s*#c01f00;/);
    expect(tokensCss).toMatch(/--color-badge-success:\s*#1f6e4a;/);
  });

  it("never lets shadcn remap the primary color away from the token", () => {
    expect(declares(globalsCss, "--color-primary")).toBe(false);
  });
});
