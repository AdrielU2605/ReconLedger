import { useEffect, useState } from "react";

const STORAGE_KEY = "reconledger.first-run-dismissed";

interface FirstRunExplainerProps {
  /** Forces the panel open regardless of prior dismissal - the Help button
   * in the app header sets this so a returning user can still reread it
   * (UX-01: "can be dismissed and restored from Help"). */
  forceOpen: boolean;
  onDismiss: () => void;
}

export function FirstRunExplainer({ forceOpen, onDismiss }: FirstRunExplainerProps) {
  const [dismissed, setDismissed] = useState(true);

  useEffect(() => {
    try {
      setDismissed(window.localStorage.getItem(STORAGE_KEY) === "true");
    } catch {
      setDismissed(false); // storage unavailable (private mode, etc.) - default to showing it
    }
  }, []);

  if (dismissed && !forceOpen) return null;

  function handleDismiss() {
    try {
      window.localStorage.setItem(STORAGE_KEY, "true");
    } catch {
      // per-viewer convenience only; nothing breaks if this can't persist
    }
    setDismissed(true);
    onDismiss();
  }

  return (
    <section className="panel" aria-labelledby="first-run-heading">
      <div className="panel-header">
        <h2 id="first-run-heading">Before you start</h2>
        <button type="button" className="dismiss-button" onClick={handleDismiss} aria-label="Dismiss this explanation">
          Dismiss
        </button>
      </div>
      <p>
        <strong>Passive reconnaissance</strong> means collecting information only from public and
        third-party sources - never by contacting the domain, IP, or CIDR block you're assessing
        directly. ReconLedger queries registries, DNS resolvers, certificate transparency logs,
        and web archives on your behalf, and will never scan, probe, or brute-force the target
        itself. Enter a domain, IP address, or CIDR block to begin - for example{" "}
        <code>example.com</code>, <code>203.0.113.0/24</code>, or <code>Example Corp</code>{" "}
        (organization search ships in a later release).
      </p>
    </section>
  );
}
