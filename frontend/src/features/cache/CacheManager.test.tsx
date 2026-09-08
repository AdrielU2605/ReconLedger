import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { CacheManager } from "./CacheManager";
import { api } from "../../api/client";
import type { CacheInventoryRead } from "../../api/types";

vi.mock("../../api/client", async () => {
  const actual = await vi.importActual<typeof import("../../api/client")>("../../api/client");
  return { ...actual, api: { ...actual.api, getCacheInventory: vi.fn(), clearCache: vi.fn() } };
});

const mockedApi = vi.mocked(api);

function makeInventory(overrides: Partial<CacheInventoryRead> = {}): CacheInventoryRead {
  return {
    total_entries: 3,
    expired_entries: 1,
    size_bytes: 2048,
    by_collector: [
      { collector: "rdap", count: 2 },
      { collector: "crtsh", count: 1 },
    ],
    ...overrides,
  };
}

describe("CacheManager", () => {
  it("renders nothing when closed", () => {
    render(<CacheManager open={false} onClose={vi.fn()} />);
    expect(mockedApi.getCacheInventory).not.toHaveBeenCalled();
    expect(screen.queryByText(/provider response cache/i)).not.toBeInTheDocument();
  });

  it("loads and shows the inventory summary and per-collector breakdown when opened", async () => {
    mockedApi.getCacheInventory.mockResolvedValue(makeInventory());
    render(<CacheManager open={true} onClose={vi.fn()} />);

    expect(await screen.findByText(/3 cached responses/i)).toBeInTheDocument();
    expect(screen.getByText(/1 already expired/i)).toBeInTheDocument();
    expect(screen.getByText(/rdap: 2/i)).toBeInTheDocument();
    expect(screen.getByText(/crtsh: 1/i)).toBeInTheDocument();
  });

  it("shows a distinct empty state when there is nothing cached", async () => {
    mockedApi.getCacheInventory.mockResolvedValue(makeInventory({ total_entries: 0, expired_entries: 0, size_bytes: 0, by_collector: [] }));
    render(<CacheManager open={true} onClose={vi.fn()} />);

    expect(await screen.findByText(/no cached provider responses/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /clear cache/i })).not.toBeInTheDocument();
  });

  it("reports what will be deleted before requiring confirmation to clear", async () => {
    mockedApi.getCacheInventory.mockResolvedValue(makeInventory());
    mockedApi.clearCache.mockResolvedValue(undefined);
    const user = userEvent.setup();
    render(<CacheManager open={true} onClose={vi.fn()} />);

    await screen.findByText(/3 cached responses/i);
    await user.click(screen.getByRole("button", { name: /^clear cache$/i }));

    expect(mockedApi.clearCache).not.toHaveBeenCalled();
    expect(screen.getByText(/clear all 3 cached responses/i)).toBeInTheDocument();

    mockedApi.getCacheInventory.mockResolvedValue(makeInventory({ total_entries: 0, expired_entries: 0, size_bytes: 0, by_collector: [] }));
    await user.click(screen.getByRole("button", { name: /confirm clear/i }));

    expect(mockedApi.clearCache).toHaveBeenCalled();
    expect(await screen.findByText(/no cached provider responses/i)).toBeInTheDocument();
  });

  it("cancelling the confirmation leaves the cache untouched", async () => {
    mockedApi.getCacheInventory.mockResolvedValue(makeInventory());
    const user = userEvent.setup();
    render(<CacheManager open={true} onClose={vi.fn()} />);

    await screen.findByText(/3 cached responses/i);
    await user.click(screen.getByRole("button", { name: /^clear cache$/i }));
    await user.click(screen.getByRole("button", { name: /^cancel$/i }));

    expect(mockedApi.clearCache).not.toHaveBeenCalled();
    expect(screen.getByText(/3 cached responses/i)).toBeInTheDocument();
  });

  it("calls onClose when Close is clicked", async () => {
    mockedApi.getCacheInventory.mockResolvedValue(makeInventory());
    const onClose = vi.fn();
    const user = userEvent.setup();
    render(<CacheManager open={true} onClose={onClose} />);

    await screen.findByText(/3 cached responses/i);
    await user.click(screen.getByRole("button", { name: /close cache panel/i }));
    expect(onClose).toHaveBeenCalled();
  });
});
