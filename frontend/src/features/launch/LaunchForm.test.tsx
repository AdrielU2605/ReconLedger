import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { LaunchForm } from "./LaunchForm";
import { api } from "../../api/client";
import type { SourceRead } from "../../api/types";

vi.mock("../../api/client", async () => {
  const actual = await vi.importActual<typeof import("../../api/client")>("../../api/client");
  return {
    ...actual,
    api: {
      ...actual.api,
      listSources: vi.fn(),
      createJob: vi.fn(),
    },
  };
});

const mockedApi = vi.mocked(api);

const READY_SOURCE: SourceRead = {
  name: "rdap",
  display_name: "RDAP",
  supported_targets: ["domain", "ip"],
  categories: ["network_footprint"],
  release: "mvp",
  state: "ready",
  key_help_url: null,
};

describe("LaunchForm", () => {
  it("keeps launch disabled until target, attestation, and a source are all set", async () => {
    mockedApi.listSources.mockResolvedValue([READY_SOURCE]);
    const user = userEvent.setup();
    render(<LaunchForm onLaunched={vi.fn()} />);

    const launchButton = await screen.findByRole("button", { name: /launch job/i });
    expect(launchButton).toBeDisabled();

    await user.type(screen.getByRole("textbox", { name: /target/i }), "example.com");
    expect(launchButton).toBeDisabled(); // attestation not yet checked

    await user.click(screen.getByText(/i own this target/i));
    await waitFor(() => expect(launchButton).toBeEnabled());
  });

  it("blocks launch and explains why for a URL-scheme input", async () => {
    mockedApi.listSources.mockResolvedValue([READY_SOURCE]);
    const user = userEvent.setup();
    render(<LaunchForm onLaunched={vi.fn()} />);

    await user.type(screen.getByRole("textbox", { name: /target/i }), "http://example.com");
    await user.click(await screen.findByText(/i own this target/i));

    expect(screen.getByText(/must not include a url scheme/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /launch job/i })).toBeDisabled();
  });

  it("explains that an organization target is not yet assessable", async () => {
    mockedApi.listSources.mockResolvedValue([READY_SOURCE]);
    const user = userEvent.setup();
    render(<LaunchForm onLaunched={vi.fn()} />);

    await user.type(screen.getByRole("textbox", { name: /target/i }), "Example Corp");
    expect(await screen.findByText(/not assessable until release 1\.1/i)).toBeInTheDocument();
  });

  it("shows a missing-key source as selectable but explains it will be skipped", async () => {
    mockedApi.listSources.mockResolvedValue([
      { ...READY_SOURCE, name: "github", display_name: "GitHub", state: "missing_key", release: "1.1" },
    ]);
    render(<LaunchForm onLaunched={vi.fn()} />);

    expect(await screen.findByText(/will be skipped rather than failing the job/i)).toBeInTheDocument();
  });

  it("calls onLaunched with the created job on success", async () => {
    mockedApi.listSources.mockResolvedValue([READY_SOURCE]);
    const createdJob = { id: "job-1", status: "queued" } as never;
    mockedApi.createJob.mockResolvedValue(createdJob);
    const onLaunched = vi.fn();
    const user = userEvent.setup();

    render(<LaunchForm onLaunched={onLaunched} />);
    await user.type(screen.getByRole("textbox", { name: /target/i }), "example.com");
    await user.click(await screen.findByText(/i own this target/i));
    await user.click(screen.getByRole("button", { name: /launch job/i }));

    await waitFor(() => expect(onLaunched).toHaveBeenCalledWith(createdJob));
  });
});
