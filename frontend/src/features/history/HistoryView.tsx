import { useEffect, useState } from "react";
import { api } from "../../api/client";
import type { JobSummary } from "../../api/types";

interface HistoryViewProps {
  onReopen: (jobId: string) => void;
}

const STATUS_LABELS: Record<string, string> = {
  queued: "Queued",
  running: "Running",
  completed: "Completed",
  completed_with_warnings: "Completed with warnings",
  failed: "Failed",
  canceled: "Canceled",
};

export function HistoryView({ onReopen }: HistoryViewProps) {
  const [jobs, setJobs] = useState<JobSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pendingDeleteId, setPendingDeleteId] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);

  function load() {
    api
      .listJobs()
      .then(setJobs)
      .catch((err) => setError(err instanceof Error ? err.message : "Failed to load job history."));
  }

  useEffect(() => {
    load();
  }, []);

  async function confirmDelete(jobId: string) {
    setDeletingId(jobId);
    try {
      await api.deleteJob(jobId);
      setJobs((prev) => (prev ? prev.filter((j) => j.id !== jobId) : prev));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to delete job.");
    } finally {
      setDeletingId(null);
      setPendingDeleteId(null);
    }
  }

  if (error) return <p className="error">{error}</p>;
  if (jobs === null) return <p>Loading history…</p>;

  return (
    <section className="panel">
      <h2>History ({jobs.length})</h2>
      {jobs.length === 0 ? (
        <p className="empty-state">No jobs yet. Launch one to see it here.</p>
      ) : (
        <ul className="history-list">
          {jobs.map((job) => (
            <li key={job.id} className="history-row">
              <div className="history-main">
                <button type="button" className="history-target" onClick={() => onReopen(job.id)}>
                  {job.target_normalized} <span className="history-target-type">({job.target_type})</span>
                </button>
                <p className="history-meta">
                  {STATUS_LABELS[job.status] ?? job.status}
                  {job.warning_count > 0 && ` · ${job.warning_count} warning${job.warning_count === 1 ? "" : "s"}`}
                  {" · "}
                  {new Date(job.created_at).toLocaleString()}
                  {" · "}
                  Sources: {job.selected_sources.join(", ")}
                </p>
                {job.scope_note && <p className="history-scope-note">Scope: {job.scope_note}</p>}
              </div>
              {pendingDeleteId === job.id ? (
                <div className="history-delete-confirm">
                  <span>Delete this job and its evidence?</span>
                  <button type="button" onClick={() => confirmDelete(job.id)} disabled={deletingId === job.id}>
                    {deletingId === job.id ? "Deleting…" : "Confirm delete"}
                  </button>
                  <button type="button" onClick={() => setPendingDeleteId(null)}>
                    Cancel
                  </button>
                </div>
              ) : (
                <button type="button" onClick={() => setPendingDeleteId(job.id)}>
                  Delete
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
