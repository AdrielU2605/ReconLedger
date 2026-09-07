import { useEffect, useRef, useState } from "react";
import { api } from "../../api/client";
import type { JobDetail } from "../../api/types";

const TERMINAL_STATUSES = new Set([
  "completed",
  "completed_with_warnings",
  "failed",
  "canceled",
]);

const POLL_INTERVAL_MS = 1500;

export type ConnectionState = "connecting" | "live" | "polling" | "stopped";

export interface UseJobResult {
  job: JobDetail | null;
  connectionState: ConnectionState;
  error: string | null;
}

/**
 * UX-05: per-collector progress via SSE, with polling fallback if the
 * connection drops. GET /api/jobs/{id} is always the authoritative source
 * (PRD 7.3) - an SSE message is only ever a "something changed, go re-fetch"
 * signal, never trusted for its payload content directly.
 */
export function useJob(jobId: string | null): UseJobResult {
  const [job, setJob] = useState<JobDetail | null>(null);
  const [connectionState, setConnectionState] = useState<ConnectionState>("connecting");
  const [error, setError] = useState<string | null>(null);
  const pollHandle = useRef<number | null>(null);

  useEffect(() => {
    if (!jobId) {
      setJob(null);
      setConnectionState("stopped");
      return;
    }

    let cancelled = false;
    setConnectionState("connecting");
    setError(null);

    const refetch = async (): Promise<JobDetail | null> => {
      try {
        const detail = await api.getJob(jobId);
        if (!cancelled) setJob(detail);
        return detail;
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : "Failed to load job.");
        return null;
      }
    };

    const stopPolling = () => {
      if (pollHandle.current !== null) {
        window.clearInterval(pollHandle.current);
        pollHandle.current = null;
      }
    };

    const startPolling = () => {
      setConnectionState("polling");
      stopPolling();
      pollHandle.current = window.setInterval(async () => {
        const detail = await refetch();
        if (detail && TERMINAL_STATUSES.has(detail.status)) {
          stopPolling();
          setConnectionState("stopped");
        }
      }, POLL_INTERVAL_MS);
    };

    void refetch();

    const source = new EventSource(api.eventsUrl(jobId));
    source.onopen = () => {
      if (!cancelled) setConnectionState("live");
    };
    source.onmessage = () => {
      void refetch().then((detail) => {
        if (detail && TERMINAL_STATUSES.has(detail.status)) {
          source.close();
          setConnectionState("stopped");
        }
      });
    };
    source.onerror = () => {
      source.close();
      if (!cancelled) startPolling();
    };

    return () => {
      cancelled = true;
      source.close();
      stopPolling();
    };
  }, [jobId]);

  return { job, connectionState, error };
}
