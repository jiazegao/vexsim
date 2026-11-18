// The run as the run bar sets it up (App.tsx): kept for the next visit, with what it names
// read from the server (a PROS project's routines, the robot on its field to draw before a
// run), a route to run, and the saved runs it's picked from and saved to.

import type { Dispatch, SetStateAction } from "react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../api";
import type { Preview, ProjectRoutines, RunConfiguration, RunProblem } from "../protocol";
import type { RunForm } from "../runform";
import { formToSpec, saveForm, specToForm } from "../runform";
import type { Pose } from "../startpose";
import { formatStart } from "../startpose";
import { startOf } from "./shared";
import type { Workspace } from "./useWorkspace";

export function useRunForm(deps: { form: RunForm; setForm: Dispatch<SetStateAction<RunForm>>; ws: Workspace; setProblem: (problem: RunProblem | null) => void }) {
  const { form, setForm, ws, setProblem } = deps;
  const { info, workspace, rescans, configurations, saveConfigurations } = ws;
  const [preview, setPreview] = useState<Preview | null>(null);
  const [routines, setRoutines] = useState<ProjectRoutines | null>(null); // the PROS project's

  // The run form is kept for the next visit, once it's been brought back from the last one (the
  // list arrives with it): saved any sooner, the empty form it starts as would replace what was kept.
  useEffect(() => {
    if (info && workspace) saveForm(info.workspace, form);
  }, [form, info, workspace]);

  // A PROS project's routines (include/custom/auton.hpp), to pick one in the run bar.
  const isProject = !!workspace?.items.some((item) => item.kind === "project" && item.path === form.program);
  useEffect(() => {
    if (!info || !isProject) {
      setRoutines(null);
      return;
    }
    let current = true;
    api
      .routines(form.program)
      .then((result) => current && setRoutines("ok" in result ? result.ok : null))
      .catch(() => current && setRoutines(null));
    return () => {
      current = false;
    };
  }, [info, isProject, form.program, rescans]);

  // The robot and field as configured, to show before a run and drag the robot's start.
  useEffect(() => {
    if (!info || !form.robot) {
      setPreview(null);
      return;
    }
    let current = true;
    api
      .preview(form.robot, form.field || null)
      .then((result) => current && setPreview("preview" in result ? result.preview : null))
      .catch(() => current && setPreview(null));
    return () => {
      current = false;
    };
  }, [info, form.robot, form.field, rescans]);

  const startPose = useMemo(() => startOf(form), [form]);
  const moveStart = useCallback(
    (pose: Pose) => {
      setForm((current) => ({ ...current, x: formatStart(pose[0]), y: formatStart(pose[1]), heading: formatStart(pose[2]) }));
    },
    [setForm],
  );

  /** The run form set up to run a route: its project's, with its robot, field and start (as
   * its setPose has it). */
  const routeForm = async (path: string): Promise<(current: RunForm) => RunForm> => {
    const project = path.split("/").slice(0, -2).join("/") || ".";
    const listed = await api.routines(project).catch(() => null);
    const route = listed && "ok" in listed ? listed.ok.routes?.find((r) => r.path === path) : undefined;
    const start = route?.start;
    return (current) => ({
      ...current,
      program: project,
      routine: "",
      route: path,
      mode: current.mode === "driver" ? "" : current.mode,
      ...(start ? { x: formatStart(start[0]), y: formatStart(start[1]), heading: formatStart(start[2]) } : {}),
      ...(route?.robot ? { robot: route.robot } : {}),
      ...(route ? { field: route.field ?? "" } : {}),
    });
  };
  /** A route to run: picked in the run bar. */
  const pickRoute = async (path: string) => setForm(await routeForm(path));

  const pickConfiguration = (name: string) => {
    const chosen = configurations.find((c) => c.name === name);
    setForm(chosen ? specToForm(chosen, chosen.name) : { ...form, config: "" });
    setProblem(null);
  };
  const saveConfiguration = async (name: string): Promise<string | null> => {
    const result = formToSpec(form);
    if ("error" in result) return result.error;
    const entry: RunConfiguration = { ...result.spec, name };
    const at = configurations.findIndex((c) => c.name === name);
    const next = at < 0 ? [...configurations, entry] : configurations.map((c, i) => (i === at ? entry : c));
    const error = await saveConfigurations(next);
    if (!error) setForm((current) => ({ ...current, config: name }));
    return error;
  };
  const deleteConfiguration = async (name: string): Promise<string | null> => {
    const error = await saveConfigurations(configurations.filter((c) => c.name !== name));
    if (!error) setForm((current) => (current.config === name ? { ...current, config: "" } : current));
    return error;
  };

  return { routines, preview, startPose, moveStart, routeForm, pickRoute, pickConfiguration, saveConfiguration, deleteConfiguration };
}
