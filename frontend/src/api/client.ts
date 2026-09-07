import type {
  ApiErrorBody,
  FindingRead,
  JobCreateRequest,
  JobDetail,
  JobSummary,
  SourceRead,
} from "./types";

export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
    this.name = "ApiError";
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
  });

  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = (await response.json()) as ApiErrorBody;
      if (body.detail) detail = body.detail;
    } catch {
      // Non-JSON error body (e.g. a network-level failure) - fall back to statusText.
    }
    throw new ApiError(response.status, detail);
  }

  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}

export const api = {
  listSources: (): Promise<SourceRead[]> => request("/api/sources"),

  createJob: (payload: JobCreateRequest): Promise<JobDetail> =>
    request("/api/jobs", { method: "POST", body: JSON.stringify(payload) }),

  listJobs: (): Promise<JobSummary[]> => request("/api/jobs"),

  getJob: (jobId: string): Promise<JobDetail> => request(`/api/jobs/${jobId}`),

  listFindings: (jobId: string): Promise<FindingRead[]> => request(`/api/jobs/${jobId}/findings`),

  cancelJob: (jobId: string): Promise<{ status: string }> =>
    request(`/api/jobs/${jobId}/cancel`, { method: "POST" }),

  deleteJob: (jobId: string): Promise<void> => request(`/api/jobs/${jobId}`, { method: "DELETE" }),

  exportUrl: (jobId: string, format: "md" | "json", mode: "summary" | "full" = "full"): string =>
    `/api/jobs/${jobId}/export?format=${format}&mode=${mode}`,

  eventsUrl: (jobId: string): string => `/api/jobs/${jobId}/events`,
};
