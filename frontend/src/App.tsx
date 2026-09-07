import { useState } from "react";
import { api } from "./api/client";
import type { JobDetail } from "./api/types";
import { LaunchForm } from "./features/launch/LaunchForm";
import { FindingsView } from "./features/findings/FindingsView";
import { FirstRunExplainer } from "./features/help/FirstRunExplainer";
import { ProgressView } from "./features/progress/ProgressView";
import { useJob } from "./features/progress/useJob";

const TERMINAL_STATUSES = new Set(["completed", "completed_with_warnings", "failed", "canceled"]);

export default function App() {
  const [activeJobId, setActiveJobId] = useState<string | null>(null);
  const [cancelling, setCancelling] = useState(false);
  const [helpForcedOpen, setHelpForcedOpen] = useState(false);
  const { job, connectionState, error } = useJob(activeJobId);

  async function handleCancel() {
    if (!activeJobId) return;
    setCancelling(true);
    try {
      await api.cancelJob(activeJobId);
    } finally {
      setCancelling(false);
    }
  }

  function handleLaunched(newJob: JobDetail) {
    setActiveJobId(newJob.id);
  }

  function handleStartOver() {
    setActiveJobId(null);
  }

  return (
    <main>
      <header>
        <div className="header-row">
          <h1>ReconLedger</h1>
          <button type="button" onClick={() => setHelpForcedOpen(true)}>
            Help
          </button>
        </div>
        <p>Passive reconnaissance, one authorized target at a time.</p>
      </header>

      <FirstRunExplainer forceOpen={helpForcedOpen} onDismiss={() => setHelpForcedOpen(false)} />

      {!activeJobId && <LaunchForm onLaunched={handleLaunched} />}

      {activeJobId && error && <p className="error">{error}</p>}

      {activeJobId && job && (
        <>
          <ProgressView
            job={job}
            connectionState={connectionState}
            onCancel={handleCancel}
            cancelling={cancelling}
          />
          {TERMINAL_STATUSES.has(job.status) && (
            <>
              <FindingsView job={job} />
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
