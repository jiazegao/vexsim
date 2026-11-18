// The folder the app is open on (App.tsx): what the server says of itself, what's in the
// folder, and its saved runs. The list is read again when asked, and whenever the window gets
// the focus back.

import type { Dispatch, SetStateAction } from "react";
import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api";
import type { AppInfo, RunConfiguration, WorkspaceInfo } from "../protocol";
import type { RunForm } from "../runform";
import { loadForm, reconcile } from "../runform";

export function useWorkspace(setForm: Dispatch<SetStateAction<RunForm>>) {
  const [info, setInfo] = useState<AppInfo | null>(null);
  const [workspace, setWorkspace] = useState<WorkspaceInfo | null>(null);
  const [scanning, setScanning] = useState(false);
  const [rescans, setRescans] = useState(0);
  const [configurations, setConfigurations] = useState<RunConfiguration[]>([]);
  const [configFile, setConfigFile] = useState(".vexsim/launch.yaml");
  const [configError, setConfigError] = useState<string | null>(null);

  const loadConfigurations = useCallback(async () => {
    try {
      const found = await api.configurations();
      setConfigurations(found.configurations);
      setConfigFile(found.file);
      setConfigError(found.error ?? null);
    } catch (error) {
      setConfigError((error as Error).message);
    }
  }, []);

  /** List the workspace again. "changed": only if the folder isn't as it was at the last
   * listing (the server tells by its stamp, reading nothing); "fresh": read every file whatever
   * the stamps say (Refresh). The list, or null if it's as it was. */
  const stamp = useRef(""); // the folder's mark at the last listing
  const scan = useCallback(
    async (infoNow: AppInfo, restore: boolean, how: "list" | "changed" | "fresh" = "list"): Promise<WorkspaceInfo | null> => {
      if (how !== "changed") setScanning(true);
      try {
        const found = await api.workspace(how === "changed" ? stamp.current : null, how === "fresh");
        if (!found) return null;
        stamp.current = found.stamp ?? "";
        setWorkspace(found);
        setForm((current) => reconcile(restore ? (loadForm(infoNow.workspace) ?? current) : current, found.items));
        setRescans((n) => n + 1);
        await loadConfigurations();
        return found;
      } finally {
        if (how !== "changed") setScanning(false);
      }
    },
    [loadConfigurations, setForm],
  );
  // The list follows the disk: looked at again whenever the window gets the focus back (a file
  // made in your editor is there when you come back to pick it).
  useEffect(() => {
    if (!info) return;
    let last = -Infinity;
    const look = () => {
      if (document.visibilityState !== "visible" || performance.now() - last < 1000) return;
      last = performance.now();
      scan(info, false, "changed").catch(() => {}); // the list stays as it was
    };
    window.addEventListener("focus", look);
    document.addEventListener("visibilitychange", look);
    return () => {
      window.removeEventListener("focus", look);
      document.removeEventListener("visibilitychange", look);
    };
  }, [info, scan]);

  const saveConfigurations = async (next: RunConfiguration[]): Promise<string | null> => {
    try {
      const saved = await api.saveConfigurations(next);
      setConfigurations(saved.configurations);
      setConfigError(saved.error ?? null);
      return null;
    } catch (error) {
      return (error as Error).message;
    }
  };

  return { info, setInfo, workspace, scanning, rescans, configurations, configFile, configError, scan, saveConfigurations };
}

export type Workspace = ReturnType<typeof useWorkspace>;
