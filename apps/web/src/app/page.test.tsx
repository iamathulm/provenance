import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import Home from "./page";

describe("Home", () => {
  it("renders the product name as the page heading inside main", () => {
    render(<Home />);

    expect(screen.getByRole("main")).toBeDefined();
    expect(screen.getByRole("heading", { level: 1, name: "Provenance" })).toBeDefined();
  });
});
