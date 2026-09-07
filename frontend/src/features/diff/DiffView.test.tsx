import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { DiffView } from "./DiffView";
import { api } from "../../api/client";
import type { DiffFindingRead, DiffResponse, JobDetail, JobSummary } from "../../api/types";

vi.mock("../../api/client", async () => {
  const actual = await vi.importActual<typeof import("../../api/client")>("../../api/client");
  return { ...actual, api: { ...actual.api, listJobs: vi.fn(), getDiff: vi.fn() } };
});

const mockedApi = vi.mocked(api);

const JOB = {
  id: "job-new",
  target_normalized: "example.com",
} as JobDetail;

function makeSummary(overrides: Partial<JobSummary> = {}): JobSummary {
  return {
    id: "job-old",
    target_input: "example.com",
    target_normalized: "example.com",
    target_type: "domain",
    status: "completed",
    selected_sources: ["rdap"],
    warning_count: 0,
    scope_note: null,
    created_at: "2026-01-01T00:00:00Z",
    started_at: null,
    finished_at: null,
    ...overrides,
  };
}

function makeDiffFinding(overrides: Partial<DiffFindingRead> = {}): DiffFindingRead {
  return {
    fingerprint: "fp-1",
    collector: "rdap",
    kind: "rdap.registration",
    title: "New registrar",
    summary: "Registrar changed",
    normalized_value: {},
    ...overrides,
  };
}

describe("DiffView", () => {
  it("shows an empty state when there is no other run against the same target", async () => {
    mockedApi.listJobs.mockResolvedValue([makeSummary({ target_normalized: "other.com" })]);
    render(<DiffView job={JOB} />);

    expect(await screen.findByText(/no other completed run/i)).toBeInTheDocument();
  });

  it("excludes jobs on different targets and the job itself from the candidate list", async () => {
    mockedApi.listJobs.mockResolvedValue([
      makeSummary({ id: "job-new", target_normalized: "example.com" }), // itself
      makeSummary({ id: "job-other-target", target_normalized: "other.com" }),
      makeSummary({ id: "job-old", target_normalized: "example.com" }),
    ]);
    render(<DiffView job={JOB} />);

    const select = await screen.findByLabelText(/compare against/i);
    expect(select).toBeInTheDocument();
    // Only "job-old" should appear as an option (plus the placeholder).
    expect(screen.getAllByRole("option")).toHaveLength(2);
  });

  it("running a comparison shows added/changed/removed/unchanged counts and groups", async () => {
    mockedApi.listJobs.mockResolvedValue([makeSummary()]);
    const diffResponse: DiffResponse = {
      added: [makeDiffFinding({ fingerprint: "fp-added", title: "New finding" })],
      removed: [],
      changed: [{ old: makeDiffFinding({ fingerprint: "fp-c", summary: "old" }), new: makeDiffFinding({ fingerprint: "fp-c", summary: "new" }) }],
      unchanged_count: 3,
      indeterminate: [],
    };
    mockedApi.getDiff.mockResolvedValue(diffResponse);
    const user = userEvent.setup();
    render(<DiffView job={JOB} />);

    await user.selectOptions(await screen.findByLabelText(/compare against/i), "job-old");
    await user.click(screen.getByRole("button", { name: /^compare$/i }));

    expect(await screen.findByText(/1 added · 1 changed · 0 removed · 3 unchanged/i)).toBeInTheDocument();
    expect(screen.getByText("New finding")).toBeInTheDocument();
    expect(mockedApi.getDiff).toHaveBeenCalledWith("job-new", "job-old");
  });

  it("indeterminate findings are shown separately with an explanation, never as removed", async () => {
    mockedApi.listJobs.mockResolvedValue([makeSummary()]);
    mockedApi.getDiff.mockResolvedValue({
      added: [],
      removed: [],
      changed: [],
      unchanged_count: 0,
      indeterminate: [makeDiffFinding({ fingerprint: "fp-indet", title: "Maybe gone" })],
    });
    const user = userEvent.setup();
    render(<DiffView job={JOB} />);

    await user.selectOptions(await screen.findByLabelText(/compare against/i), "job-old");
    await user.click(screen.getByRole("button", { name: /^compare$/i }));

    expect(await screen.findByText("Maybe gone")).toBeInTheDocument();
    expect(screen.getByText(/did not complete in both runs/i)).toBeInTheDocument();
    expect(screen.getByText(/0 removed/i)).toBeInTheDocument();
  });
});
