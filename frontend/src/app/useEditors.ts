// The editors open beside the pages (App.tsx): robot and field configs, and routes in the
// autonomous maker. Which are open, which have changes not saved, what's being made new, and
// what a calibration asks an editor to write in.

import type { Dispatch, SetStateAction } from "react";
import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import type { ConfigRequest } from "../components/ConfigEditor";
import type { WorkspaceItem } from "../protocol";
import type { RunForm } from "../runform";
import type { Workspace } from "./useWorkspace";

export function useEditors(deps: { ws: Workspace; setForm: Dispatch<SetStateAction<RunForm>>; setPage: Dispatch<SetStateAction<string>> }) {
  const { ws, setForm, setPage } = deps;
  const { info, scan } = ws;
  const [openConfigs, setOpenConfigs] = useState<string[]>([]); // configs (and routes) open in editors
  const [openRoutes, setOpenRoutes] = useState<string[]>([]); // those that are routes, in the autonomous maker
  const [designing, setDesigning] = useState<string[]>([]); // opened in their Design view
  const [newRobot, setNewRobot] = useState(false); // the "New robot…" dialog is open
  const [newRoute, setNewRoute] = useState(false); // the "New route…" dialog is open
  const [overrideRequests, setOverrideRequests] = useState<Record<string, ConfigRequest>>({});
  const [unsaved, setUnsaved] = useState<Record<string, boolean>>({});
  const [closing, setClosing] = useState<string | null>(null); // asking before closing it

  const openConfig = (path: string, design = false) => {
    if (design) setDesigning((list) => (list.includes(path) ? list : [...list, path]));
    setOpenConfigs((open) => (open.includes(path) ? open : [...open, path]));
    setPage(path);
  };
  /** A route, open in the autonomous maker (in a tab, as a config is). */
  const openRoute = (path: string) => {
    setOpenRoutes((open) => (open.includes(path) ? open : [...open, path]));
    setOpenConfigs((open) => (open.includes(path) ? open : [...open, path]));
    setPage(path);
  };
  /** A route "New route…" made (or a mirrored copy): listed, and open in the maker. */
  const routeCreated = async (path: string) => {
    setNewRoute(false);
    if (info) await scan(info, false);
    openRoute(path);
  };
  /** A robot "New robot…" made: picked for the next run, and open in its Design view. */
  const robotCreated = async (path: string) => {
    setNewRobot(false);
    if (info) await scan(info, false);
    setForm((current) => ({ ...current, config: "", robot: path }));
    openConfig(path, true);
  };
  /** A workspace file copied beside itself (the list shows it): the copy's path. */
  const duplicateItem = async (item: WorkspaceItem): Promise<string> => {
    const made = await api.duplicateFile(item.path);
    if (info) await scan(info, false);
    return made.path;
  };
  /** A workspace file deleted: its editor closes, if it's open, and the run bar lets it go. */
  const deleteItem = async (item: WorkspaceItem) => {
    await api.deleteFile(item.path);
    if (openConfigs.includes(item.path)) closeConfig(item.path);
    if (info) await scan(info, false);
  };
  const closeConfig = (path: string) => {
    setOpenConfigs((open) => open.filter((p) => p !== path));
    setOpenRoutes((open) => open.filter((p) => p !== path));
    setUnsaved(({ [path]: _, ...rest }) => rest);
    setClosing(null);
    setPage((current) => (current === path ? "simulate" : current));
  };
  const askToClose = (path: string) => {
    if (unsaved[path]) {
      setPage(path);
      setClosing(path);
    } else closeConfig(path);
  };
  const markUnsaved = useCallback((path: string, dirty: boolean) => {
    setUnsaved((all) => (!!all[path] === dirty ? all : { ...all, [path]: dirty }));
  }, []);
  const anyUnsaved = Object.values(unsaved).some(Boolean);
  useEffect(() => {
    if (!anyUnsaved) return;
    const warn = (event: BeforeUnloadEvent) => event.preventDefault(); // the browser asks first
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [anyUnsaved]);

  /** A calibration's fitted values, added to a robot config in its editor (to save there). */
  const applyOverrides = async (robot: string, overrides: Record<string, number>) => {
    openConfig(robot);
    setOverrideRequests((all) => ({ ...all, [robot]: { id: (all[robot]?.id ?? 0) + 1, overrides } }));
  };

  /** What a calibration session's fit found, written into its robot's config in its editor (to save there). */
  const applySession = async (robot: string, session: string) => {
    openConfig(robot);
    setOverrideRequests((all) => ({ ...all, [robot]: { id: (all[robot]?.id ?? 0) + 1, session } }));
  };

  return {
    openConfigs,
    openRoutes,
    designing,
    newRobot,
    setNewRobot,
    newRoute,
    setNewRoute,
    overrideRequests,
    unsaved,
    closing,
    setClosing,
    openConfig,
    openRoute,
    routeCreated,
    robotCreated,
    duplicateItem,
    deleteItem,
    closeConfig,
    askToClose,
    markUnsaved,
    applyOverrides,
    applySession,
  };
}
