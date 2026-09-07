import { useEffect, useState } from "react";
import { api, ApiError } from "../../api/client";
import type { JobDetail, SourceRead } from "../../api/types";
import { classifyPreview } from "./classifyPreview";

interface LaunchFormProps {
  onLaunched: (job: JobDetail) => void;
}

const ATTESTATION_TEXT =
  "I own this target, or I have been given written authorization to assess it. " +
  "I understand ReconLedger only queries third-party providers and never contacts the target directly.";

export function LaunchForm({ onLaunched }: LaunchFormProps) {
  const [target, setTarget] = useState("");
  const [scopeNote, setScopeNote] = useState("");
  const [attested, setAttested] = useState(false);
  const [sources, setSources] = useState<SourceRead[]>([]);
  const [selectedSources, setSelectedSources] = useState<Set<string>>(new Set());
  const [sourcesError, setSourcesError] = useState<string | null>(null);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    let cancelled = false;
    api
      .listSources()
      .then((list) => {
        if (cancelled) return;
        setSources(list);
        setSelectedSources(new Set(list.filter((s) => s.release === "mvp").map((s) => s.name)));
      })
      .catch((err) => {
        if (!cancelled) setSourcesError(err instanceof Error ? err.message : "Failed to load sources.");
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const preview = classifyPreview(target);
  const previewBlocksLaunch = preview.targetType === "invalid" || preview.targetType === "organization";
  const canLaunch =
    target.trim().length > 0 &&
    !previewBlocksLaunch &&
    attested &&
    selectedSources.size > 0 &&
    !submitting;

  function toggleSource(name: string) {
    setSelectedSources((prev) => {
      const next = new Set(prev);
      if (next.has(name)) next.delete(name);
      else next.add(name);
      return next;
    });
  }

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    if (!canLaunch) return;
    setSubmitting(true);
    setSubmitError(null);
    try {
      const job = await api.createJob({
        target: target.trim(),
        selected_sources: Array.from(selectedSources),
        scope_note: scopeNote.trim() || null,
        attestation_confirmed: attested,
      });
      onLaunched(job);
    } catch (err) {
      setSubmitError(err instanceof ApiError ? err.message : "Could not launch the job.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="launch-form" aria-label="Launch a passive reconnaissance job">
      <section className="panel" aria-labelledby="first-run-heading">
        <h2 id="first-run-heading">Before you start</h2>
        <p>
          ReconLedger performs <strong>passive</strong> reconnaissance only: it queries public and
          third-party data providers (registries, certificate transparency logs, DNS resolvers) and
          never sends any request to the domain, IP, or CIDR block you enter. Examples of valid
          input: <code>example.com</code>, <code>203.0.113.0/24</code>, or <code>Example Corp</code>{" "}
          (organization search ships in a later release).
        </p>
      </section>

      <section className="panel">
        <label htmlFor="target-input">Target (domain, IP, or CIDR)</label>
        <input
          id="target-input"
          type="text"
          value={target}
          onChange={(e) => setTarget(e.target.value)}
          placeholder="example.com"
          autoComplete="off"
          aria-describedby="target-preview"
        />
        <p id="target-preview" className={previewBlocksLaunch ? "preview preview-error" : "preview"}>
          {preview.message || "Enter a domain, IP address, or CIDR block."}
        </p>
      </section>

      <section className="panel">
        <h2>Sources</h2>
        {sourcesError && <p className="error">{sourcesError}</p>}
        <ul className="source-list">
          {sources.map((source) => (
            <li key={source.name} className="source-row">
              <label>
                <input
                  type="checkbox"
                  checked={selectedSources.has(source.name)}
                  onChange={() => toggleSource(source.name)}
                />
                {source.display_name}
              </label>
              <span className={`badge badge-${source.state}`}>
                {source.state === "ready" && "Ready — no key required"}
                {source.state === "missing_key" &&
                  "Missing key — will be skipped rather than failing the job"}
                {source.state === "unavailable" && "Unavailable"}
                {source.state === "not_applicable" && "Not applicable to this target"}
              </span>
              {source.key_help_url && (
                <a href={source.key_help_url} target="_blank" rel="noopener noreferrer">
                  Key setup
                </a>
              )}
            </li>
          ))}
        </ul>
      </section>

      <section className="panel">
        <h2>Authorization</h2>
        <label className="attestation">
          <input type="checkbox" checked={attested} onChange={(e) => setAttested(e.target.checked)} />
          {ATTESTATION_TEXT}
        </label>
        <label htmlFor="scope-note">Scope note (optional)</label>
        <textarea
          id="scope-note"
          value={scopeNote}
          onChange={(e) => setScopeNote(e.target.value)}
          maxLength={2000}
          rows={3}
        />
      </section>

      {submitError && (
        <p role="alert" className="error">
          {submitError}
        </p>
      )}

      <button type="submit" disabled={!canLaunch}>
        {submitting ? "Launching…" : "Launch job"}
      </button>
    </form>
  );
}
