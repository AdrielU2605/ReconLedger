import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { FirstRunExplainer } from "./FirstRunExplainer";

beforeEach(() => {
  window.localStorage.clear();
});

describe("FirstRunExplainer", () => {
  it("is visible on first visit", async () => {
    render(<FirstRunExplainer forceOpen={false} onDismiss={vi.fn()} />);
    expect(await screen.findByText(/passive reconnaissance/i)).toBeInTheDocument();
  });

  it("states the app contacts third-party providers only, with the required examples", async () => {
    render(<FirstRunExplainer forceOpen={false} onDismiss={vi.fn()} />);
    const panel = await screen.findByRole("region", { name: /before you start/i });
    expect(panel.textContent).toMatch(/example\.com/);
    expect(panel.textContent).toMatch(/203\.0\.113\.0\/24/);
    expect(panel.textContent).toMatch(/Example Corp/);
  });

  it("dismissing hides it and persists the dismissal", async () => {
    const onDismiss = vi.fn();
    const user = userEvent.setup();
    render(<FirstRunExplainer forceOpen={false} onDismiss={onDismiss} />);

    await user.click(await screen.findByRole("button", { name: /dismiss/i }));

    expect(screen.queryByText(/passive reconnaissance/i)).not.toBeInTheDocument();
    expect(onDismiss).toHaveBeenCalled();
    expect(window.localStorage.getItem("reconledger.first-run-dismissed")).toBe("true");
  });

  it("a prior dismissal keeps it hidden on the next visit", async () => {
    window.localStorage.setItem("reconledger.first-run-dismissed", "true");
    render(<FirstRunExplainer forceOpen={false} onDismiss={vi.fn()} />);

    await waitFor(() => expect(screen.queryByText(/passive reconnaissance/i)).not.toBeInTheDocument());
  });

  it("forceOpen restores it even after a prior dismissal (the Help button)", async () => {
    window.localStorage.setItem("reconledger.first-run-dismissed", "true");
    render(<FirstRunExplainer forceOpen={true} onDismiss={vi.fn()} />);

    expect(await screen.findByText(/passive reconnaissance/i)).toBeInTheDocument();
  });
});
