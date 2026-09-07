import { useEffect, useMemo, useState } from "react";
import { api } from "../../api/client";
import type { SubdomainRowRead } from "../../api/types";

interface SubdomainWorkspaceProps {
  jobId: string;
}

type SortKey = "subdomain" | "source_count" | "first_seen_at" | "last_seen_at";
type SortDirection = "asc" | "desc";

function compareValues(a: SubdomainRowRead, b: SubdomainRowRead, key: SortKey): number {
  const av = a[key];
  const bv = b[key];
  if (av === null) return bv === null ? 0 : 1;
  if (bv === null) return -1;
  if (typeof av === "number" && typeof bv === "number") return av - bv;
  return String(av).localeCompare(String(bv));
}

export function SubdomainWorkspace({ jobId }: SubdomainWorkspaceProps) {
  const [rows, setRows] = useState<SubdomainRowRead[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [filterText, setFilterText] = useState("");
  const [sortKey, setSortKey] = useState<SortKey>("subdomain");
  const [sortDirection, setSortDirection] = useState<SortDirection>("asc");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [copyFeedback, setCopyFeedback] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    api
      .listSubdomains(jobId)
      .then((data) => {
        if (!cancelled) setRows(data);
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : "Failed to load subdomains.");
      });
    return () => {
      cancelled = true;
    };
  }, [jobId]);

  const filteredAndSorted = useMemo(() => {
    if (!rows) return [];
    const needle = filterText.trim().toLowerCase();
    const filtered = needle
      ? rows.filter(
          (r) => r.subdomain.toLowerCase().includes(needle) || r.sources.some((s) => s.toLowerCase().includes(needle)),
        )
      : rows;
    const sorted = [...filtered].sort((a, b) => compareValues(a, b, sortKey));
    if (sortDirection === "desc") sorted.reverse();
    return sorted;
  }, [rows, filterText, sortKey, sortDirection]);

  function toggleSort(key: SortKey) {
    if (key === sortKey) {
      setSortDirection((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      setSortDirection("asc");
    }
  }

  function toggleSelected(subdomain: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(subdomain)) next.delete(subdomain);
      else next.add(subdomain);
      return next;
    });
  }

  async function copyToClipboard(subdomains: string[], label: string) {
    const text = subdomains.join("\n");
    try {
      await navigator.clipboard.writeText(text);
      setCopyFeedback(`Copied ${subdomains.length} ${label}.`);
    } catch {
      setCopyFeedback("Copy failed - your browser blocked clipboard access.");
    }
  }

  if (error) return <p className="error">{error}</p>;
  if (rows === null) return <p>Loading subdomains…</p>;

  const sortIndicator = (key: SortKey) => (key === sortKey ? (sortDirection === "asc" ? " ▲" : " ▼") : "");

  return (
    <section className="panel">
      <h2>Subdomains ({rows.length})</h2>

      <div className="subdomain-toolbar">
        <label htmlFor="subdomain-filter">Filter</label>
        <input
          id="subdomain-filter"
          type="text"
          value={filterText}
          onChange={(e) => setFilterText(e.target.value)}
          placeholder="Filter by subdomain or source"
        />
        <button
          type="button"
          onClick={() => copyToClipboard(Array.from(selected), "selected")}
          disabled={selected.size === 0}
        >
          Copy selected ({selected.size})
        </button>
        <button
          type="button"
          onClick={() => copyToClipboard(filteredAndSorted.map((r) => r.subdomain), "filtered")}
          disabled={filteredAndSorted.length === 0}
        >
          Copy filtered ({filteredAndSorted.length})
        </button>
        <a href={api.subdomainsCsvUrl(jobId)} download={`reconledger-${jobId}-subdomains.csv`}>
          Download CSV
        </a>
      </div>
      {copyFeedback && (
        <p role="status" className="copy-feedback">
          {copyFeedback}
        </p>
      )}

      {rows.length === 0 ? (
        <p className="empty-state">No subdomain evidence in this job (crt.sh or archive sources may not have run).</p>
      ) : filteredAndSorted.length === 0 ? (
        <p className="empty-state">No subdomains match this filter.</p>
      ) : (
        <table className="subdomain-table">
          <thead>
            <tr>
              <th scope="col">
                <span className="visually-hidden">Select</span>
              </th>
              <th scope="col">
                <button type="button" onClick={() => toggleSort("subdomain")}>
                  Subdomain{sortIndicator("subdomain")}
                </button>
              </th>
              <th scope="col">
                <button type="button" onClick={() => toggleSort("source_count")}>
                  Sources{sortIndicator("source_count")}
                </button>
              </th>
              <th scope="col">
                <button type="button" onClick={() => toggleSort("first_seen_at")}>
                  First seen{sortIndicator("first_seen_at")}
                </button>
              </th>
              <th scope="col">
                <button type="button" onClick={() => toggleSort("last_seen_at")}>
                  Last seen{sortIndicator("last_seen_at")}
                </button>
              </th>
              <th scope="col">Wildcard</th>
              <th scope="col">In scope</th>
            </tr>
          </thead>
          <tbody>
            {filteredAndSorted.map((row) => (
              <tr key={row.subdomain}>
                <td>
                  <input
                    type="checkbox"
                    checked={selected.has(row.subdomain)}
                    onChange={() => toggleSelected(row.subdomain)}
                    aria-label={`Select ${row.subdomain}`}
                  />
                </td>
                <th scope="row">{row.subdomain}</th>
                <td>
                  {row.source_count} ({row.sources.join(", ")})
                </td>
                <td>{row.first_seen_at ?? "—"}</td>
                <td>{row.last_seen_at ?? "—"}</td>
                <td>{row.wildcard ? "Yes" : "No"}</td>
                <td>{row.in_scope ? "Yes" : "No"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
