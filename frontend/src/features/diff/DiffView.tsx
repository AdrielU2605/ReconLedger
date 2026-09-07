import { useEffect, useState } from "react";
import { api, ApiError } from "../../api/client";
import type { DiffFindingRead, DiffResponse, JobDetail, JobSummary } from "../../api/types";

interface DiffViewProps {
  job: JobDetail;
}

function DiffFindingItem({ finding }: { finding: DiffFindingRead }) {
  return (
    <li className="finding">
      <p className="finding-title">{finding.title}</p>
      <p className="finding-summary">{finding.summary}</p>
      <p className="finding-meta">
        Source: {finding.collector} · Kind: {finding.kind}
      </p>
    </li>
  );
}

export function DiffView({ job }: DiffViewProps) {
  const [candidates, setCandidates] = useState<JobSummary[] | null>(null);
  const [againstId, setAgainstId] = useState<string>("");
  const [diff, setDiff] = useState<DiffResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    let cancelled = false;
    api
      .listJobs()
      .then((jobs) => {
        if (cancelled) return;
        const sameTarget = jobs.filter(
          (j) =>
            j.id !== job.id &&
            j.target_normalized === job.target_normalized &&
            ["completed", "completed_with_warnings"].includes(j.status),
        );
        setCandidates(sameTarget);
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : "Failed to load prior runs.");
      });
    return () => {
      cancelled = true;
    };
  }, [job.id, job.target_normalized]);

  async function runDiff() {
    if (!againstId) return;
    setLoading(true);
    setError(null);
    setDiff(null);
    try {
      const result = await api.getDiff(job.id, againstId);
      setDiff(result);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to compute diff.");
    } finally {
      setLoading(false);
    }
  }

  if (error) return <p className="error">{error}</p>;
  if (candidates === null) return <p>Loading prior runs…</p>;

  return (
    <section className="panel">
      <h2>Compare with an earlier run</h2>
      {candidates.length === 0 ? (
        <p className="empty-state">No other completed run against this same target exists yet.</p>
      ) : (
        <>
          <div className="diff-toolbar">
            <label htmlFor="diff-against">Compare against</label>
            <select id="diff-against" value={againstId} onChange={(e) => setAgainstId(e.target.value)}>
              <option value="">Select a prior run…</option>
              {candidates.map((c) => (
                <option key={c.id} value={c.id}>
                  {new Date(c.created_at).toLocaleString()} ({c.status})
                </option>
              ))}
            </select>
            <button type="button" onClick={runDiff} disabled={!againstId || loading}>
              {loading ? "Comparing…" : "Compare"}
            </button>
          </div>

          {diff && (
            <div className="diff-results">
              <p role="status">
                {diff.added.length} added · {diff.changed.length} changed · {diff.removed.length} removed ·{" "}
                {diff.unchanged_count} unchanged
                {diff.indeterminate.length > 0 && ` · ${diff.indeterminate.length} indeterminate`}
              </p>

              <h3>Added ({diff.added.length})</h3>
              {diff.added.length === 0 ? (
                <p className="empty-state">Nothing new.</p>
              ) : (
                <ul className="finding-list">
                  {diff.added.map((f) => (
                    <DiffFindingItem key={f.fingerprint} finding={f} />
                  ))}
                </ul>
              )}

              <h3>Changed ({diff.changed.length})</h3>
              {diff.changed.length === 0 ? (
                <p className="empty-state">Nothing changed.</p>
              ) : (
                <ul className="finding-list">
                  {diff.changed.map((pair) => (
                    <li key={pair.new.fingerprint} className="finding">
                      <p className="finding-title">{pair.new.title}</p>
                      <p className="finding-summary">Was: {pair.old.summary}</p>
                      <p className="finding-summary">Now: {pair.new.summary}</p>
                    </li>
                  ))}
                </ul>
              )}

              <h3>Removed ({diff.removed.length})</h3>
              {diff.removed.length === 0 ? (
                <p className="empty-state">Nothing removed.</p>
              ) : (
                <ul className="finding-list">
                  {diff.removed.map((f) => (
                    <DiffFindingItem key={f.fingerprint} finding={f} />
                  ))}
                </ul>
              )}

              {diff.indeterminate.length > 0 && (
                <>
                  <h3>Indeterminate ({diff.indeterminate.length})</h3>
                  <p className="empty-state">
                    A source did not complete in both runs, so these cannot be confidently labeled added or
                    removed.
                  </p>
                  <ul className="finding-list">
                    {diff.indeterminate.map((f) => (
                      <DiffFindingItem key={f.fingerprint} finding={f} />
                    ))}
                  </ul>
                </>
              )}
            </div>
          )}
        </>
      )}
    </section>
  );
}
