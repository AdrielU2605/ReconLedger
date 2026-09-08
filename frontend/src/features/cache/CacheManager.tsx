import { useEffect, useState } from "react";
import { api } from "../../api/client";
import type { CacheInventoryRead } from "../../api/types";

interface CacheManagerProps {
  open: boolean;
  onClose: () => void;
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

/** FR-12: "A Clear cache action reports what will be deleted before
 * confirmation." This is a manual, explicit purge of every cached provider
 * response, distinct from the automatic sweep that only removes entries
 * once they've already expired. */
export function CacheManager({ open, onClose }: CacheManagerProps) {
  const [inventory, setInventory] = useState<CacheInventoryRead | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [clearing, setClearing] = useState(false);

  function load() {
    setError(null);
    api
      .getCacheInventory()
      .then(setInventory)
      .catch((err) => setError(err instanceof Error ? err.message : "Failed to load cache inventory."));
  }

  useEffect(() => {
    if (open) load();
  }, [open]);

  if (!open) return null;

  async function handleClear() {
    setClearing(true);
    try {
      await api.clearCache();
      setConfirming(false);
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to clear the cache.");
    } finally {
      setClearing(false);
    }
  }

  return (
    <section className="panel" aria-labelledby="cache-manager-heading">
      <div className="panel-header">
        <h2 id="cache-manager-heading">Provider response cache</h2>
        <button type="button" className="dismiss-button" onClick={onClose} aria-label="Close cache panel">
          Close
        </button>
      </div>

      {error && <p className="error">{error}</p>}

      {inventory === null && !error ? (
        <p>Loading…</p>
      ) : inventory ? (
        <>
          <p>
            {inventory.total_entries === 0
              ? "No cached provider responses."
              : `${inventory.total_entries} cached response${inventory.total_entries === 1 ? "" : "s"} (${formatBytes(inventory.size_bytes)}), ${inventory.expired_entries} already expired.`}
          </p>
          {inventory.by_collector.length > 0 && (
            <ul className="source-list">
              {inventory.by_collector.map((row) => (
                <li key={row.collector} className="source-row">
                  {row.collector}: {row.count}
                </li>
              ))}
            </ul>
          )}

          {inventory.total_entries > 0 &&
            (confirming ? (
              <div className="history-delete-confirm">
                <span>
                  Clear all {inventory.total_entries} cached response{inventory.total_entries === 1 ? "" : "s"}?
                  The next job will re-fetch from providers.
                </span>
                <button type="button" onClick={handleClear} disabled={clearing}>
                  {clearing ? "Clearing…" : "Confirm clear"}
                </button>
                <button type="button" onClick={() => setConfirming(false)} disabled={clearing}>
                  Cancel
                </button>
              </div>
            ) : (
              <button type="button" onClick={() => setConfirming(true)}>
                Clear cache
              </button>
            ))}
        </>
      ) : null}
    </section>
  );
}
