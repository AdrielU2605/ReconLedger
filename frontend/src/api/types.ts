// Generated from the backend's live OpenAPI schema (backend/openapi.json,
// produced by backend/scripts/dump_openapi.py) via openapi-typescript into
// ./generated/schema.d.ts. Both files are committed, and CI regenerates
// them and diffs against what's committed - see .github/workflows/ci.yml's
// "contract" job - so a change to a Pydantic model that isn't matched by a
// regeneration fails the build (PRD 10.1's contract-drift check).
//
// These are just ergonomic aliases; nothing here is hand-typed against the
// backend's shapes anymore; that job belongs entirely to the generator.
import type { components } from "./generated/schema";

export type TargetType = components["schemas"]["TargetType"];
export type JobStatus = components["schemas"]["JobStatus"];
export type CollectorStatus = components["schemas"]["CollectorStatus"];
export type Category = components["schemas"]["Category"];
export type Confidence = components["schemas"]["Confidence"];

export type CollectorRunRead = components["schemas"]["CollectorRunRead"];
export type JobSummary = components["schemas"]["JobSummary"];
export type JobDetail = components["schemas"]["JobDetail"];
export type FindingRead = components["schemas"]["FindingRead"];
export type SourceRead = components["schemas"]["SourceRead"];
export type SubdomainRowRead = components["schemas"]["SubdomainRowRead"];
export type JobCreateRequest = components["schemas"]["JobCreateRequest"];
export type DiffFindingRead = components["schemas"]["DiffFindingRead"];
export type DiffChangedPair = components["schemas"]["DiffChangedPair"];
export type DiffResponse = components["schemas"]["DiffResponse"];
export type CacheCollectorSummary = components["schemas"]["CacheCollectorSummary"];
export type CacheInventoryRead = components["schemas"]["CacheInventoryRead"];

// Not part of the OpenAPI schema: a validation error body (FastAPI's
// default exception handler shape) and the SSE message payload shape.
export interface ApiErrorBody {
  detail: string;
}

export interface JobEventPayload {
  event_type: string;
  collector: string | null;
  payload: Record<string, unknown>;
  created_at: string;
}
