import { useEffect, useState } from "react";
import type { ConnectionState } from "./useJob";
import type { JobDetail } from "../../api/types";

interface ProgressViewProps {
  job: JobDetail;
  connectionState: ConnectionState;
  onCancel: () => void;
  cancelling: boolean;
  onRetryCollector: (collectorName: string) => void;
  retryingCollector: string | null;
}

const STATUS_LABELS: Record<string, string> = {
  queued: "Queued",
  running: "Running",
  done: "Done",
  failed: "Failed",
  skipped_no_key: "Skipped (no key)",
  not_applicable: "Not applicable",
  interrupted: "Interrupted (resuming)",
};

/** UX-10: a running job shows elapsed time ticking rather than an
 * indefinite spinner, so a long-running job never looks stalled. */
function useElapsedSeconds(startedAt: string | null, active: boolean): number | null {
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    if (!active || !startedAt) return;
    const handle = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(handle);
  }, [active, startedAt]);

  if (!startedAt) return null;
  return Math.max(0, Math.floor((now - Date.parse(startedAt)) / 1000));
}

function formatElapsed(totalSeconds: number): string {
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${minutes}:${seconds.toString().padStart(2, "0")}`;
}

export function ProgressView({
  job,
  connectionState,
  onCancel,
  cancelling,
  onRetryCollector,
  retryingCollector,
}: ProgressViewProps) {
  const isTerminal = ["completed", "completed_with_warnings", "failed", "canceled"].includes(job.status);
  const elapsedSeconds = useElapsedSeconds(job.started_at, !isTerminal);

  return (
    <section className="panel" aria-live="polite">
      <h2>
        Job progress — {job.target_normalized} ({job.target_type})
      </h2>

      {job.status === "failed" && (
        <p role="alert" className="fatal-state">
          This job failed: none of the selected sources returned a result. See the reasons below - a
          retry may succeed if the cause was transient (e.g. a provider timeout).
        </p>
      )}

      <p>
        Status: <strong>{job.status.replace(/_/g, " ")}</strong>
        {!isTerminal && elapsedSeconds !== null && ` · ${formatElapsed(elapsedSeconds)} elapsed`}
        {" · "}
        <span className={`connection connection-${connectionState}`}>
          {connectionState === "live" && "live updates"}
          {connectionState === "polling" && "reconnecting… (polling)"}
          {connectionState === "connecting" && "connecting…"}
          {connectionState === "stopped" && "finished"}
        </span>
      </p>

      <table className="collector-table">
        <thead>
          <tr>
            <th scope="col">Source</th>
            <th scope="col">State</th>
            <th scope="col">Findings</th>
            <th scope="col">Reason</th>
            <th scope="col">Action</th>
          </tr>
        </thead>
        <tbody>
          {job.collector_runs.map((run) => (
            <tr key={run.collector}>
              <th scope="row">{run.collector}</th>
              <td>
                {STATUS_LABELS[run.status] ?? run.status}
                {run.cache_hit && run.status === "done" ? " (cached)" : ""}
              </td>
              <td>{run.finding_count}</td>
              <td>{run.safe_error_message ?? "—"}</td>
              <td>
                {isTerminal && run.status === "failed" && (
                  <button
                    type="button"
                    onClick={() => onRetryCollector(run.collector)}
                    disabled={retryingCollector === run.collector}
                  >
                    {retryingCollector === run.collector ? "Retrying…" : "Retry"}
                  </button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      {!isTerminal && (
        <button type="button" onClick={onCancel} disabled={cancelling}>
          {cancelling ? "Cancelling…" : "Cancel job"}
        </button>
      )}
    </section>
  );
}
