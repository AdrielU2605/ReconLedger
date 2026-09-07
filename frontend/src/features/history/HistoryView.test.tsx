import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { HistoryView } from "./HistoryView";
import { api } from "../../api/client";
import type { JobSummary } from "../../api/types";

vi.mock("../../api/client", async () => {
  const actual = await vi.importActual<typeof import("../../api/client")>("../../api/client");
  return { ...actual, api: { ...actual.api, listJobs: vi.fn(), deleteJob: vi.fn() } };
});

const mockedApi = vi.mocked(api);

function makeSummary(overrides: Partial<JobSummary> = {}): JobSummary {
  return {
    id: "job-1",
    target_input: "example.com",
    target_normalized: "example.com",
    target_type: "domain",
    status: "completed",
    selected_sources: ["rdap", "dns_doh"],
    warning_count: 0,
    scope_note: null,
    created_at: "2026-01-01T00:00:00Z",
    started_at: "2026-01-01T00:00:01Z",
    finished_at: "2026-01-01T00:00:05Z",
    ...overrides,
  };
}

describe("HistoryView", () => {
  it("shows an empty state when there is no history yet", async () => {
    mockedApi.listJobs.mockResolvedValue([]);
    render(<HistoryView onReopen={vi.fn()} />);

    expect(await screen.findByText(/no jobs yet/i)).toBeInTheDocument();
  });

  it("lists a job with its status, warning count, sources, and scope note", async () => {
    mockedApi.listJobs.mockResolvedValue([
      makeSummary({ status: "completed_with_warnings", warning_count: 2, scope_note: "authorized pentest" }),
    ]);
    render(<HistoryView onReopen={vi.fn()} />);

    expect(await screen.findByText(/example\.com/)).toBeInTheDocument();
    expect(screen.getByText(/completed with warnings/i)).toBeInTheDocument();
    expect(screen.getByText(/2 warnings/i)).toBeInTheDocument();
    expect(screen.getByText(/rdap, dns_doh/i)).toBeInTheDocument();
    expect(screen.getByText(/authorized pentest/i)).toBeInTheDocument();
  });

  it("clicking the target reopens that job", async () => {
    mockedApi.listJobs.mockResolvedValue([makeSummary()]);
    const onReopen = vi.fn();
    const user = userEvent.setup();
    render(<HistoryView onReopen={onReopen} />);

    await user.click(await screen.findByRole("button", { name: /example\.com/i }));
    expect(onReopen).toHaveBeenCalledWith("job-1");
  });

  it("deleting a job requires confirmation before calling the API", async () => {
    mockedApi.listJobs.mockResolvedValue([makeSummary()]);
    mockedApi.deleteJob.mockResolvedValue(undefined);
    const user = userEvent.setup();
    render(<HistoryView onReopen={vi.fn()} />);

    await screen.findByText(/example\.com/);
    await user.click(screen.getByRole("button", { name: /^delete$/i }));

    expect(mockedApi.deleteJob).not.toHaveBeenCalled();
    expect(screen.getByText(/delete this job and its evidence/i)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /confirm delete/i }));
    expect(mockedApi.deleteJob).toHaveBeenCalledWith("job-1");
    expect(await screen.findByText(/no jobs yet/i)).toBeInTheDocument();
  });

  it("cancelling the delete confirmation leaves the job in place", async () => {
    mockedApi.listJobs.mockResolvedValue([makeSummary()]);
    const user = userEvent.setup();
    render(<HistoryView onReopen={vi.fn()} />);

    await screen.findByText(/example\.com/);
    await user.click(screen.getByRole("button", { name: /^delete$/i }));
    await user.click(screen.getByRole("button", { name: /^cancel$/i }));

    expect(mockedApi.deleteJob).not.toHaveBeenCalled();
    expect(screen.getByText(/example\.com/)).toBeInTheDocument();
  });
});
