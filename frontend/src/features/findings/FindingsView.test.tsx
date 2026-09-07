import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { FindingsView } from "./FindingsView";
import { api } from "../../api/client";
import type { FindingRead, JobDetail } from "../../api/types";

vi.mock("../../api/client", async () => {
  const actual = await vi.importActual<typeof import("../../api/client")>("../../api/client");
  return { ...actual, api: { ...actual.api, listFindings: vi.fn() } };
});

const mockedApi = vi.mocked(api);

const JOB = {
  id: "job-1",
  collector_runs: [{ collector: "rdap" } as JobDetail["collector_runs"][number]],
} as JobDetail;

function makeFinding(overrides: Partial<FindingRead> = {}): FindingRead {
  return {
    id: "finding-1",
    collector: "rdap",
    category: "network_footprint",
    kind: "rdap.registrar",
    title: "Registrar: Example Registrar Inc.",
    summary: "The domain is registered through Example Registrar Inc.",
    normalized_value: {},
    raw_evidence: { secret_looking_field: "<script>alert(1)</script>" },
    source_url: "https://rdap.example/domain/example.com",
    provider_observed_at: null,
    retrieved_at: "2026-01-01T00:00:00Z",
    confidence: null,
    fingerprint: "abc123",
    ...overrides,
  };
}

describe("FindingsView", () => {
  it("groups findings under the correct category heading", async () => {
    mockedApi.listFindings.mockResolvedValue([makeFinding()]);
    render(<FindingsView job={JOB} />);

    expect(await screen.findByText(/network footprint \(1\)/i)).toBeInTheDocument();
    expect(screen.getByText(/technology stack \(0\)/i)).toBeInTheDocument();
  });

  it("shows an empty-state message for a category with no findings", async () => {
    mockedApi.listFindings.mockResolvedValue([]);
    render(<FindingsView job={JOB} />);

    const emptyMessages = await screen.findAllByText(/no findings were returned/i);
    expect(emptyMessages.length).toBeGreaterThan(0);
  });

  it("renders raw evidence as inert text behind a disclosure, never as HTML", async () => {
    mockedApi.listFindings.mockResolvedValue([makeFinding()]);
    const user = userEvent.setup();
    render(<FindingsView job={JOB} />);

    const disclosure = await screen.findByText(/raw evidence/i);
    await user.click(disclosure);

    // The <script> tag must appear as literal visible text, not be parsed as markup.
    expect(screen.getByText(/<script>alert\(1\)<\/script>/)).toBeInTheDocument();
    expect(document.querySelector("script[data-injected]")).toBeNull();
  });

  it("links to the evidence URL rather than the raw target", async () => {
    mockedApi.listFindings.mockResolvedValue([makeFinding()]);
    render(<FindingsView job={JOB} />);

    const link = await screen.findByRole("link", { name: /evidence url/i });
    expect(link).toHaveAttribute("href", "https://rdap.example/domain/example.com");
    expect(link).toHaveAttribute("rel", expect.stringContaining("noopener"));
  });

  it("distinguishes 'no findings match filters' from 'no findings in the job'", async () => {
    // Baseline (unfiltered) call has one finding; the filtered call (after
    // typing a search term) returns none - the empty state must say so.
    mockedApi.listFindings.mockImplementation((_jobId, query = {}) =>
      Promise.resolve(query.q ? [] : [makeFinding()]),
    );
    const user = userEvent.setup();
    render(<FindingsView job={JOB} />);

    await screen.findByText(/network footprint \(1\)/i);
    await user.type(screen.getByLabelText(/search evidence/i), "nothing-like-this");

    expect(await screen.findByText(/no findings match these filters/i)).toBeInTheDocument();
  });

  it("shows a result count that reflects filtering", async () => {
    mockedApi.listFindings.mockImplementation((_jobId, query = {}) =>
      Promise.resolve(query.category ? [] : [makeFinding()]),
    );
    const user = userEvent.setup();
    render(<FindingsView job={JOB} />);

    await screen.findByText(/1 result/i);
    await user.selectOptions(screen.getByLabelText(/^category$/i), "leaked_data");

    expect(await screen.findByText(/0 results \(filtered from 1\)/i)).toBeInTheDocument();
  });

  it("clear all resets the filters and re-fetches the unfiltered list", async () => {
    mockedApi.listFindings.mockImplementation((_jobId, query = {}) =>
      Promise.resolve(query.q ? [] : [makeFinding()]),
    );
    const user = userEvent.setup();
    render(<FindingsView job={JOB} />);

    await screen.findByText(/network footprint \(1\)/i);
    await user.type(screen.getByLabelText(/search evidence/i), "nothing-like-this");
    await screen.findByText(/no findings match these filters/i);

    await user.click(await screen.findByRole("button", { name: /clear all/i }));

    expect(await screen.findByText(/network footprint \(1\)/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /clear all/i })).not.toBeInTheDocument();
  });
});
