import { useEffect, useState } from "react";
import { api } from "../../api/client";
import type { Category, FindingRead, JobDetail } from "../../api/types";

interface FindingsViewProps {
  job: JobDetail;
}

const CATEGORY_LABELS: Record<Category, string> = {
  network_footprint: "Network Footprint",
  technology_stack: "Technology Stack",
  human_layer: "Human Layer",
  leaked_data: "Leaked Data",
};

const CATEGORY_ORDER: Category[] = [
  "network_footprint",
  "technology_stack",
  "human_layer",
  "leaked_data",
];

function groupByCategory(findings: FindingRead[]): Map<Category, FindingRead[]> {
  const groups = new Map<Category, FindingRead[]>();
  for (const category of CATEGORY_ORDER) groups.set(category, []);
  for (const finding of findings) {
    groups.get(finding.category)?.push(finding);
  }
  return groups;
}

export function FindingsView({ job }: FindingsViewProps) {
  const [findings, setFindings] = useState<FindingRead[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    api
      .listFindings(job.id)
      .then((list) => {
        if (!cancelled) setFindings(list);
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : "Failed to load findings.");
      });
    return () => {
      cancelled = true;
    };
  }, [job.id]);

  if (error) return <p className="error">{error}</p>;
  if (findings === null) return <p>Loading evidence…</p>;

  const groups = groupByCategory(findings);
  const attemptedCollectors = new Set(job.collector_runs.map((r) => r.collector));

  return (
    <section className="panel">
      <h2>Evidence</h2>
      <div className="export-buttons">
        <a href={api.exportUrl(job.id, "md", "summary")} download={`reconledger-${job.id}.md`}>
          Download Markdown
        </a>
        <a href={api.exportUrl(job.id, "json", "full")} download={`reconledger-${job.id}.json`}>
          Download JSON
        </a>
      </div>

      {CATEGORY_ORDER.map((category) => {
        const items = groups.get(category) ?? [];
        return (
          <div key={category} className="category-group">
            <h3>
              {CATEGORY_LABELS[category]} ({items.length})
            </h3>
            {items.length === 0 && (
              <p className="empty-state">
                {attemptedCollectors.size === 0
                  ? "No sources were attempted."
                  : "No findings were returned in this category for the sources that ran."}
              </p>
            )}
            <ul className="finding-list">
              {items.map((finding) => (
                <li key={finding.id} className="finding">
                  <p className="finding-title">{finding.title}</p>
                  <p className="finding-summary">{finding.summary}</p>
                  <p className="finding-meta">
                    Source: {finding.collector} · Retrieved: {new Date(finding.retrieved_at).toLocaleString()}
                    {finding.confidence && ` · Confidence: ${finding.confidence}`}
                  </p>
                  <a href={finding.source_url} target="_blank" rel="noopener noreferrer">
                    Evidence URL
                  </a>
                  <details>
                    <summary>Raw evidence</summary>
                    {/* Rendered as inert preformatted text only - never
                        injected as HTML (PRD 8.2 / UX-06). */}
                    <pre className="raw-evidence">{JSON.stringify(finding.raw_evidence, null, 2)}</pre>
                  </details>
                </li>
              ))}
            </ul>
          </div>
        );
      })}
    </section>
  );
}
