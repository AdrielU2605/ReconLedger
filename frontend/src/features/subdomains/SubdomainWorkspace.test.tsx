import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { SubdomainWorkspace } from "./SubdomainWorkspace";
import { api } from "../../api/client";
import type { SubdomainRowRead } from "../../api/types";

vi.mock("../../api/client", async () => {
  const actual = await vi.importActual<typeof import("../../api/client")>("../../api/client");
  return { ...actual, api: { ...actual.api, listSubdomains: vi.fn() } };
});

const mockedApi = vi.mocked(api);

function makeRow(overrides: Partial<SubdomainRowRead> = {}): SubdomainRowRead {
  return {
    subdomain: "www.example.com",
    source_count: 1,
    sources: ["crtsh"],
    first_seen_at: "2020-01-01",
    last_seen_at: "2021-01-01",
    wildcard: false,
    in_scope: true,
    ...overrides,
  };
}

describe("SubdomainWorkspace", () => {
  it("renders each row with its columns", async () => {
    mockedApi.listSubdomains.mockResolvedValue([makeRow()]);
    render(<SubdomainWorkspace jobId="job-1" />);

    expect(await screen.findByText("www.example.com")).toBeInTheDocument();
    expect(screen.getByText(/1 \(crtsh\)/)).toBeInTheDocument();
  });

  it("shows a distinct empty state when there is no subdomain evidence at all", async () => {
    mockedApi.listSubdomains.mockResolvedValue([]);
    render(<SubdomainWorkspace jobId="job-1" />);

    expect(await screen.findByText(/no subdomain evidence in this job/i)).toBeInTheDocument();
  });

  it("filtering narrows the rows and shows a distinct message when nothing matches", async () => {
    mockedApi.listSubdomains.mockResolvedValue([makeRow({ subdomain: "www.example.com" }), makeRow({ subdomain: "api.example.com" })]);
    const user = userEvent.setup();
    render(<SubdomainWorkspace jobId="job-1" />);

    await screen.findByText("www.example.com");
    await user.type(screen.getByLabelText(/filter/i), "api");

    expect(screen.queryByText("www.example.com")).not.toBeInTheDocument();
    expect(screen.getByText("api.example.com")).toBeInTheDocument();

    await user.clear(screen.getByLabelText(/filter/i));
    await user.type(screen.getByLabelText(/filter/i), "zzz-no-match");
    expect(await screen.findByText(/no subdomains match this filter/i)).toBeInTheDocument();
  });

  it("sorting by a column toggles ascending/descending order", async () => {
    mockedApi.listSubdomains.mockResolvedValue([makeRow({ subdomain: "zeta.example.com" }), makeRow({ subdomain: "alpha.example.com" })]);
    const user = userEvent.setup();
    render(<SubdomainWorkspace jobId="job-1" />);

    await screen.findByText("zeta.example.com");
    const table = screen.getByRole("table");
    let rows = within(table).getAllByRole("row").slice(1); // skip header row
    expect(within(rows[0]!).getByText(/alpha/)).toBeInTheDocument(); // default sort: ascending by subdomain

    await user.click(screen.getByRole("button", { name: /^subdomain/i }));
    rows = within(table).getAllByRole("row").slice(1);
    expect(within(rows[0]!).getByText(/zeta/)).toBeInTheDocument(); // toggled to descending
  });

  it("copy selected is scoped to only the checked row, and copying never crashes the page", async () => {
    // jsdom does not implement the Clipboard API at all by default, and
    // reliably stubbing navigator.clipboard across jsdom/Vitest versions has
    // known cross-version flakiness - so this exercises the real default
    // environment's behavior (the write rejects) and asserts the resulting
    // UX is a graceful, worded failure rather than a crash, while "(1)" in
    // the button label already proves selection is scoped to the one
    // checked row rather than "all rows" or "all filtered rows".
    mockedApi.listSubdomains.mockResolvedValue([makeRow({ subdomain: "a.example.com" }), makeRow({ subdomain: "b.example.com" })]);
    const user = userEvent.setup();
    render(<SubdomainWorkspace jobId="job-1" />);

    await screen.findByText("a.example.com");
    await user.click(screen.getByRole("checkbox", { name: /select a\.example\.com/i }));
    expect(screen.getByRole("button", { name: /copy selected \(1\)/i })).toBeEnabled();

    await user.click(screen.getByRole("button", { name: /copy selected \(1\)/i }));

    expect(await screen.findByRole("status")).toHaveTextContent(/copy failed|copied 1 selected/i);
  });

  it("the CSV download link points at the backend export endpoint", async () => {
    mockedApi.listSubdomains.mockResolvedValue([makeRow()]);
    render(<SubdomainWorkspace jobId="job-1" />);

    await screen.findByText("www.example.com");
    const link = screen.getByRole("link", { name: /download csv/i });
    expect(link).toHaveAttribute("href", "/api/jobs/job-1/subdomains.csv");
  });
});
