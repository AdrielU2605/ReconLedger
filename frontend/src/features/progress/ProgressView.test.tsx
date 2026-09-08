import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { ProgressView } from "./ProgressView";
import type { JobDetail } from "../../api/types";

function makeJob(overrides: Partial<JobDetail> = {}): JobDetail {
  return {
    id: "job-1",
    target_input: "example.com",
    target_normalized: "example.com",
    target_type: "domain",
    status: "running",
    selected_sources: ["rdap"],
    warning_count: 0,
    scope_note: null,
    created_at: "2026-01-01T00:00:00Z",
    started_at: "2026-01-01T00:00:01Z",
    finished_at: null,
    attestation_text: "...",
    attestation_version: "1",
    attestation_time: "2026-01-01T00:00:00Z",
    collector_runs: [
      {
        collector: "rdap",
        status: "done",
        attempt_count: 1,
        cache_hit: true,
        finding_count: 3,
        safe_error_code: null,
        safe_error_message: null,
        started_at: "2026-01-01T00:00:01Z",
        finished_at: "2026-01-01T00:00:02Z",
      },
    ],
    ...overrides,
  };
}

describe("ProgressView", () => {
  it("shows per-collector status, finding count, and a cached indicator", () => {
    render(<ProgressView job={makeJob()} connectionState="live" onCancel={vi.fn()} cancelling={false} onRetryCollector={vi.fn()} retryingCollector={null} />);
    expect(screen.getByText("rdap")).toBeInTheDocument();
    expect(screen.getByText(/done \(cached\)/i)).toBeInTheDocument();
    expect(screen.getByText("3")).toBeInTheDocument();
  });

  it("shows the plain-English failure reason for a non-success collector", () => {
    const job = makeJob({
      collector_runs: [
        {
          collector: "crtsh",
          status: "failed",
          attempt_count: 3,
          cache_hit: false,
          finding_count: 0,
          safe_error_code: "provider_timeout",
          safe_error_message: "crtsh exceeded its collector time budget.",
          started_at: "2026-01-01T00:00:01Z",
          finished_at: "2026-01-01T00:01:31Z",
        },
      ],
    });
    render(<ProgressView job={job} connectionState="live" onCancel={vi.fn()} cancelling={false} onRetryCollector={vi.fn()} retryingCollector={null} />);
    expect(screen.getByText(/exceeded its collector time budget/i)).toBeInTheDocument();
  });

  it("indicates reconnection via polling when SSE has dropped", () => {
    render(<ProgressView job={makeJob()} connectionState="polling" onCancel={vi.fn()} cancelling={false} onRetryCollector={vi.fn()} retryingCollector={null} />);
    expect(screen.getByText(/reconnecting/i)).toBeInTheDocument();
  });

  it("offers cancel for a non-terminal job and calls onCancel when clicked", async () => {
    const onCancel = vi.fn();
    const user = userEvent.setup();
    render(
      <ProgressView
        job={makeJob({ status: "running" })}
        connectionState="live"
        onCancel={onCancel}
        cancelling={false}
        onRetryCollector={vi.fn()}
        retryingCollector={null}
      />,
    );

    await user.click(screen.getByRole("button", { name: /cancel job/i }));
    expect(onCancel).toHaveBeenCalled();
  });

  it("hides the cancel button once the job reaches a terminal state", () => {
    render(<ProgressView job={makeJob({ status: "completed" })} connectionState="stopped" onCancel={vi.fn()} cancelling={false} onRetryCollector={vi.fn()} retryingCollector={null} />);
    expect(screen.queryByRole("button", { name: /cancel job/i })).not.toBeInTheDocument();
  });

  it("offers retry only for a failed collector once the job is terminal, and calls onRetryCollector", async () => {
    const onRetryCollector = vi.fn();
    const user = userEvent.setup();
    const job = makeJob({
      status: "completed_with_warnings",
      collector_runs: [
        {
          collector: "crtsh",
          status: "failed",
          attempt_count: 1,
          cache_hit: false,
          finding_count: 0,
          safe_error_code: "provider_timeout",
          safe_error_message: "crtsh exceeded its collector time budget.",
          started_at: "2026-01-01T00:00:01Z",
          finished_at: "2026-01-01T00:01:31Z",
        },
        {
          collector: "rdap",
          status: "done",
          attempt_count: 1,
          cache_hit: false,
          finding_count: 2,
          safe_error_code: null,
          safe_error_message: null,
          started_at: "2026-01-01T00:00:01Z",
          finished_at: "2026-01-01T00:00:02Z",
        },
      ],
    });
    render(
      <ProgressView
        job={job}
        connectionState="stopped"
        onCancel={vi.fn()}
        cancelling={false}
        onRetryCollector={onRetryCollector}
        retryingCollector={null}
      />,
    );

    const retryButtons = screen.getAllByRole("button", { name: /^retry$/i });
    expect(retryButtons).toHaveLength(1);
    await user.click(retryButtons[0] as HTMLElement);
    expect(onRetryCollector).toHaveBeenCalledWith("crtsh");
  });

  it("does not offer retry for a failed collector while the job is still running", () => {
    const job = makeJob({
      status: "running",
      collector_runs: [
        {
          collector: "crtsh",
          status: "failed",
          attempt_count: 1,
          cache_hit: false,
          finding_count: 0,
          safe_error_code: "provider_timeout",
          safe_error_message: "crtsh exceeded its collector time budget.",
          started_at: "2026-01-01T00:00:01Z",
          finished_at: "2026-01-01T00:01:31Z",
        },
      ],
    });
    render(
      <ProgressView
        job={job}
        connectionState="live"
        onCancel={vi.fn()}
        cancelling={false}
        onRetryCollector={vi.fn()}
        retryingCollector={null}
      />,
    );
    expect(screen.queryByRole("button", { name: /^retry$/i })).not.toBeInTheDocument();
  });
});
