import type { ConnectionState } from "./useJob";
import type { JobDetail } from "../../api/types";

interface ProgressViewProps {
  job: JobDetail;
  connectionState: ConnectionState;
  onCancel: () => void;
  cancelling: boolean;
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

export function ProgressView({ job, connectionState, onCancel, cancelling }: ProgressViewProps) {
  const isTerminal = ["completed", "completed_with_warnings", "failed", "canceled"].includes(job.status);

  return (
    <section className="panel" aria-live="polite">
      <h2>
        Job progress — {job.target_normalized} ({job.target_type})
      </h2>
      <p>
        Status: <strong>{job.status.replace(/_/g, " ")}</strong>
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
