import { useEffect } from "react";

/**
 * Tiny UI-only bridge: the canonical Application Workspace owns its own state and
 * API boundaries. The operator shell may request that existing launcher to open
 * without duplicating draft/application logic.
 */
export default function ApplicationWorkspaceEventBridge() {
  useEffect(() => {
    const openWorkspace = (event: Event) => {
      const customEvent = event as CustomEvent<{ silverJobId?: number | null }>;
      if (customEvent.detail?.silverJobId != null) return;
      const launcher = document.querySelector<HTMLButtonElement>(
        ".demo-application-launcher:not(:disabled)",
      );
      launcher?.click();
    };
    window.addEventListener("product-v1:open-application-workspace", openWorkspace);
    return () => window.removeEventListener(
      "product-v1:open-application-workspace",
      openWorkspace,
    );
  }, []);
  return null;
}
