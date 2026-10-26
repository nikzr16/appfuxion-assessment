import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { ThemeToggle } from "./ThemeToggle.tsx";

describe("ThemeToggle", () => {
  it("switches theme, remembers it and returns to the system setting", async () => {
    render(<ThemeToggle />);
    const user = userEvent.setup();
    const html = document.documentElement;

    expect(screen.getByRole("radio", { name: "System theme" })).toHaveAttribute("aria-checked", "true");
    expect(html).not.toHaveClass("dark");

    await user.click(screen.getByRole("radio", { name: "Dark theme" }));
    expect(html).toHaveClass("dark");
    expect(localStorage.getItem("theme")).toBe("dark");

    await user.click(screen.getByRole("radio", { name: "Light theme" }));
    expect(html).not.toHaveClass("dark");
    expect(localStorage.getItem("theme")).toBe("light");

    await user.click(screen.getByRole("radio", { name: "System theme" }));
    expect(localStorage.getItem("theme")).toBeNull();
  });

  it("starts from the saved preference", () => {
    localStorage.setItem("theme", "dark");
    render(<ThemeToggle />);

    expect(screen.getByRole("radio", { name: "Dark theme" })).toHaveAttribute("aria-checked", "true");
    expect(document.documentElement).toHaveClass("dark");
  });
});
