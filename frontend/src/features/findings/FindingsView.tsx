import { useEffect, useMemo, useState } from "react";
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

const DEBOUNCE_MS = 300;

function groupByCategory(findings: FindingRead[]): Map<Category, FindingRead[]> {
  const groups = new Map<Category, FindingRead[]>();
  for (const category of CATEGORY_ORDER) groups.set(category, []);
  for (const finding of findings) {
    groups.get(finding.category)?.push(finding);
  }
  return groups;
}

export function FindingsView({ job }: FindingsViewProps) {
  const [baseline, setBaseline] = useState<FindingRead[] | null>(null);
  const [findings, setFindings] = useState<FindingRead[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [searchInput, setSearchInput] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [categoryFilter, setCategoryFilter] = useState<Category | "all">("all");
  const [collectorFilter, setCollectorFilter] = useState<string>("all");

  // Baseline (unfiltered) load, once - lets empty states distinguish "no
  // findings in the job" from "no findings match these filters" (UX-08).
  useEffect(() => {
    let cancelled = false;
    api
      .listFindings(job.id)
      .then((list) => {
        if (!cancelled) setBaseline(list);
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : "Failed to load findings.");
      });
    return () => {
      cancelled = true;
    };
  }, [job.id]);

  useEffect(() => {
    const handle = window.setTimeout(() => setDebouncedSearch(searchInput), DEBOUNCE_MS);
    return () => window.clearTimeout(handle);
  }, [searchInput]);

  const hasActiveFilter = debouncedSearch.trim() !== "" || categoryFilter !== "all" || collectorFilter !== "all";

  useEffect(() => {
    let cancelled = false;
    api
      .listFindings(job.id, {
        q: debouncedSearch.trim() || undefined,
        category: categoryFilter === "all" ? undefined : categoryFilter,
        collector: collectorFilter === "all" ? undefined : collectorFilter,
      })
      .then((list) => {
        if (!cancelled) setFindings(list);
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : "Search failed.");
      });
    return () => {
      cancelled = true;
    };
  }, [job.id, debouncedSearch, categoryFilter, collectorFilter]);

  const collectorNames = useMemo(
    () => Array.from(new Set(job.collector_runs.map((r) => r.collector))).sort(),
    [job.collector_runs],
  );

  function clearAll() {
    setSearchInput("");
    setDebouncedSearch("");
    setCategoryFilter("all");
    setCollectorFilter("all");
  }

  if (error) return <p className="error">{error}</p>;
  if (findings === null || baseline === null) return <p>Loading evidence…</p>;

  const groups = groupByCategory(findings);
  const baselineGroups = groupByCategory(baseline);
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

      <div className="search-toolbar">
        <label htmlFor="finding-search">Search evidence</label>
        <input
          id="finding-search"
          type="text"
          value={searchInput}
          onChange={(e) => setSearchInput(e.target.value)}
          placeholder="Search summaries, values, URLs, raw evidence…"
        />
        <label htmlFor="category-filter">Category</label>
        <select id="category-filter" value={categoryFilter} onChange={(e) => setCategoryFilter(e.target.value as Category | "all")}>
          <option value="all">All categories</option>
          {CATEGORY_ORDER.map((c) => (
            <option key={c} value={c}>
              {CATEGORY_LABELS[c]}
            </option>
          ))}
        </select>
        <label htmlFor="collector-filter">Source</label>
        <select id="collector-filter" value={collectorFilter} onChange={(e) => setCollectorFilter(e.target.value)}>
          <option value="all">All sources</option>
          {collectorNames.map((name) => (
            <option key={name} value={name}>
              {name}
            </option>
          ))}
        </select>
        {hasActiveFilter && (
          <button type="button" onClick={clearAll}>
            Clear all
          </button>
        )}
      </div>
      <p role="status" className="result-count">
        {findings.length} result{findings.length === 1 ? "" : "s"}
        {hasActiveFilter ? ` (filtered from ${baseline.length})` : ""}
      </p>

      {CATEGORY_ORDER.map((category) => {
        const items = groups.get(category) ?? [];
        const baselineItems = baselineGroups.get(category) ?? [];
        return (
          <div key={category} className="category-group">
            <h3>
              {CATEGORY_LABELS[category]} ({items.length})
            </h3>
            {items.length === 0 && (
              <p className="empty-state">
                {hasActiveFilter && baselineItems.length > 0
                  ? "No findings match these filters."
                  : attemptedCollectors.size === 0
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
