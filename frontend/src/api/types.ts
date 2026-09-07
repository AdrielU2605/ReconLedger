// Mirrors backend/app/models/api.py and app/models/enums.py. Hand-written for
// CP4's vertical slice; CP7 replaces this file with a client generated from
// the OpenAPI schema and adds a CI check that fails on drift.

export type TargetType = "domain" | "ip" | "cidr" | "organization";

export type JobStatus =
  | "queued"
  | "running"
  | "completed"
  | "completed_with_warnings"
  | "failed"
  | "canceled";

export type CollectorStatus =
  | "queued"
  | "running"
  | "done"
  | "failed"
  | "skipped_no_key"
  | "not_applicable"
  | "interrupted";

export type Category =
  | "network_footprint"
  | "technology_stack"
  | "human_layer"
  | "leaked_data";

export type Confidence = "low" | "medium" | "high";

export interface CollectorRunRead {
  collector: string;
  status: CollectorStatus;
  attempt_count: number;
  cache_hit: boolean;
  finding_count: number;
  safe_error_code: string | null;
  safe_error_message: string | null;
  started_at: string | null;
  finished_at: string | null;
}

export interface JobSummary {
  id: string;
  target_input: string;
  target_normalized: string;
  target_type: TargetType;
  status: JobStatus;
  selected_sources: string[];
  scope_note: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}

export interface JobDetail extends JobSummary {
  attestation_text: string;
  attestation_version: string;
  attestation_time: string;
  collector_runs: CollectorRunRead[];
}

export interface FindingRead {
  id: string;
  collector: string;
  category: Category;
  kind: string;
  title: string;
  summary: string;
  normalized_value: Record<string, unknown>;
  raw_evidence: Record<string, unknown>;
  source_url: string;
  provider_observed_at: string | null;
  retrieved_at: string;
  confidence: Confidence | null;
  fingerprint: string;
}

export type SourceState = "ready" | "missing_key" | "unavailable" | "not_applicable";

export interface SourceRead {
  name: string;
  display_name: string;
  supported_targets: TargetType[];
  categories: Category[];
  release: "mvp" | "1.1";
  state: SourceState;
  key_help_url: string | null;
}

export interface JobCreateRequest {
  target: string;
  selected_sources: string[];
  scope_note: string | null;
  attestation_confirmed: boolean;
}

export interface ApiErrorBody {
  detail: string;
}

export interface JobEventPayload {
  event_type: string;
  collector: string | null;
  payload: Record<string, unknown>;
  created_at: string;
}
