import { useState } from "react";
import { api } from "./api/client";
import type { JobDetail } from "./api/types";
import { LaunchForm } from "./features/launch/LaunchForm";
import { CacheManager } from "./features/cache/CacheManager";
import { DiffView } from "./features/diff/DiffView";
import { FindingsView } from "./features/findings/FindingsView";
import { FirstRunExplainer } from "./features/help/FirstRunExplainer";
import { HistoryView } from "./features/history/HistoryView";
import { useOnlineStatus } from "./features/offline/useOnlineStatus";
import { ProgressView } from "./features/progress/ProgressView";
import { SubdomainWorkspace } from "./features/subdomains/SubdomainWorkspace";
import { useJob } from "./features/progress/useJob";
import { useTheme } from "./theme";

const TERMINAL_STATUSES = new Set(["completed", "completed_with_warnings", "failed", "canceled"]);

type View = "launch" | "history";

export default function App() {
  const [view, setView] = useState<View>("launch");
  const [activeJobId, setActiveJobId] = useState<string | null>(null);
  const [cancelling, setCancelling] = useState(false);
  const [retryingCollector, setRetryingCollector] = useState<string | null>(null);
  const [helpForcedOpen, setHelpForcedOpen] = useState(false);
  const [cacheManagerOpen, setCacheManagerOpen] = useState(false);
  const { job, connectionState, error, reconnect } = useJob(activeJobId);
  const { theme, setTheme } = useTheme();
  const online = useOnlineStatus();

  async function handleCancel() {
    if (!activeJobId) return;
    setCancelling(true);
    try {
      await api.cancelJob(activeJobId);
    } finally {
      setCancelling(false);
    }
  }

  async function handleRetryCollector(collectorName: string) {
    if (!activeJobId) return;
    setRetryingCollector(collectorName);
    try {
      await api.retryCollector(activeJobId, collectorName);
      reconnect();
    } finally {
      setRetryingCollector(null);
    }
  }

  function handleLaunched(newJob: JobDetail) {
    setActiveJobId(newJob.id);
    setView("launch");
  }

  function handleStartOver() {
    setActiveJobId(null);
    setView("launch");
  }

  function handleReopen(jobId: string) {
    setActiveJobId(jobId);
    setView("launch");
  }

  return (
    <main>
      <header>
        <div className="header-row">
          <h1>ReconLedger</h1>
          <nav className="header-nav">
            <button
              type="button"
              onClick={() => {
                setActiveJobId(null);
                setView("launch");
              }}
            >
              New job
            </button>
            <button type="button" onClick={() => setView("history")}>
              History
            </button>
            <button type="button" onClick={() => setHelpForcedOpen(true)}>
              Help
            </button>
            <button type="button" onClick={() => setCacheManagerOpen(true)}>
              Cache
            </button>
            <label className="theme-select">
              <span className="visually-hidden">Theme</span>
              <select value={theme} onChange={(e) => setTheme(e.target.value as typeof theme)}>
                <option value="system">Theme: System</option>
                <option value="light">Theme: Light</option>
                <option value="dark">Theme: Dark</option>
              </select>
            </label>
          </nav>
        </div>
        <p>Passive reconnaissance, one authorized target at a time.</p>
      </header>

      {!online && (
        <p role="alert" className="offline-banner">
          You're offline. Recon Ledger only reaches its own local backend, but that request still
          needs your network - reconnect to keep using it.
        </p>
      )}

      <FirstRunExplainer forceOpen={helpForcedOpen} onDismiss={() => setHelpForcedOpen(false)} />

      <CacheManager open={cacheManagerOpen} onClose={() => setCacheManagerOpen(false)} />

      {view === "history" && !activeJobId && <HistoryView onReopen={handleReopen} />}

      {view === "launch" && !activeJobId && <LaunchForm onLaunched={handleLaunched} />}

      {activeJobId && error && <p className="error">{error}</p>}

      {activeJobId && job && (
        <>
          <ProgressView
            job={job}
            connectionState={connectionState}
            onCancel={handleCancel}
            cancelling={cancelling}
            onRetryCollector={handleRetryCollector}
            retryingCollector={retryingCollector}
          />
          {TERMINAL_STATUSES.has(job.status) && (
            <>
              <FindingsView job={job} />
              <SubdomainWorkspace jobId={job.id} />
              <DiffView job={job} />
              <button type="button" onClick={handleStartOver}>
                Start a new job
              </button>
            </>
          )}
        </>
      )}
    </main>
  );
}
