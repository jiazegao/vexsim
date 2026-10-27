import { useEffect, useMemo, useState } from "react";
import { api } from "../api";
import { JobStatus } from "../components/JobPanel";
import { Lines, Problems } from "../components/ConsolePanel";
import { isActive, latest, useJob } from "../jobs";
import type { Editor } from "../problems";
import { compilerProblems, shortPath } from "../problems";
import type { WorkspaceInfo } from "../protocol";

/** `vexsim build` and `vexsim doctor`: the workspace's PROS projects, built (or built for a
 * debugger), with their errors as links; and a check of the compiler. */
export function BuildPage(props: { workspace: WorkspaceInfo | null; root: string; editor: Editor; project: string | null; onProject: (path: string) => void }) {
  const projects = useMemo(() => props.workspace?.items.filter((i) => i.kind === "project") ?? [], [props.workspace]);
  const build = useJob();
  const doctor = useJob();
  const building = isActive(build.job?.state);
  const [problem, setProblem] = useState<string | null>(null);
  const { follow: followBuild } = build;
  const { follow: followDoctor } = doctor;

  useEffect(() => {
    // pick up a build or a check that's still going (from before a reload, or a run's build)
    api
      .jobs()
      .then((jobs) => {
        const running = latest(jobs, "build", true);
        if (running) followBuild(running.id);
        const checking = latest(jobs, "doctor", true);
        if (checking) followDoctor(checking.id);
      })
      .catch(() => {});
  }, [followBuild, followDoctor]);

  const start = async (project: string, debug: boolean) => {
    props.onProject(project);
    const failed = await build.start({ kind: "build", project, debug });
    setProblem(failed?.error ?? null);
  };

  const job = build.job;
  const builtProject = typeof job?.params.project === "string" ? job.params.project : null;
  const result = job?.state === "succeeded" ? (job.result as { executable: string; linked: boolean; compiled: number; total: number; seconds: number; debug?: boolean } | null) : null;
  const problems = useMemo(() => compilerProblems((job?.log ?? []).join("\n")), [job?.log]);
  const doctorLines = doctor.job?.log ?? [];

  return (
    <div className="page" data-testid="build-page">
      <header className="page-head">
        <h1>Build</h1>
        <p className="muted">
          PROS projects build as they do for a run (only what changed compiles again); a debug build (<code>-O0 -g</code>) is for stepping
          through the code in a debugger. Same as <code>vexsim build</code> and <code>vexsim doctor</code>.
        </p>
      </header>
      <section className="card">
        <h2>PROS projects</h2>
        {projects.length === 0 ? (
          <p className="muted">No PROS projects (folders with a project.pros) in this workspace.</p>
        ) : (
          <table className="data" data-testid="projects">
            <thead>
              <tr>
                <th>Project</th>
                <th>Folder</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {projects.map((project) => (
                <tr key={project.path} className={props.project === project.path ? "chosen" : undefined}>
                  <td>
                    <b>{project.name}</b> <span className="muted small">{project.detail}</span>
                  </td>
                  <td className="muted small">{project.path}</td>
                  <td>
                    <div className="row-actions">
                      <button type="button" className="small" disabled={building} onClick={() => start(project.path, false)} data-testid={`build-${project.path}`}>
                        Build
                      </button>
                      <button type="button" className="small" disabled={building} onClick={() => start(project.path, true)} title="Compile with -O0 -g, for a debugger">
                        Debug build
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {problem && (
          <div className="problem" role="alert">
            <strong>
              <span aria-hidden="true">⚠</span> {problem}
            </strong>
          </div>
        )}
        {job && (
          <div className="stack">
            <h3>
              {job.title}
              {builtProject && <span className="muted small"> · {shortPath(props.root, builtProject)}</span>}
            </h3>
            <JobStatus job={job} onCancel={build.cancel} log={false} />
            {result && (
              <p data-testid="build-result">
                {result.linked ? `Built: ${result.compiled} of ${result.total} sources compiled` : "Up to date: nothing to compile"} in {result.seconds.toFixed(1)} s
                {result.debug ? ", for a debugger" : ""}. <span className="muted small">{result.executable}</span>
              </p>
            )}
            {problems.length > 0 && <Problems problems={problems} root={props.root} editor={props.editor} testid="build-problems" />}
            {job.log.length > 0 && (
              <Lines lines={job.log.map((text) => ({ kind: "build", text }))} root={props.root} editor={props.editor} empty="The build's output appears here." testid="build-log" />
            )}
          </div>
        )}
      </section>
      <section className="card">
        <h2>Compiler</h2>
        <p className="muted">Is there a g++ that builds PROS projects for vexsim, and do they run? It compiles and runs a small test program.</p>
        <div className="actions">
          <button type="button" onClick={() => doctor.start({ kind: "doctor" })} disabled={isActive(doctor.job?.state)} data-testid="doctor">
            Check the compiler
          </button>
        </div>
        {doctor.job && (
          <div className="stack">
            <JobStatus job={doctor.job} onCancel={doctor.cancel} log={false} />
            <ul className="checks" data-testid="doctor-lines">
              {doctorLines.map((line, i) => {
                const ok = line.startsWith("[ ok ]");
                const bad = line.startsWith("[FAIL]");
                return (
                  <li key={i} className={ok ? "ok" : bad ? "bad" : undefined}>
                    {ok && <span aria-label="passed">✓</span>}
                    {bad && <span aria-label="failed">✗</span>}
                    <span>{ok || bad ? line.slice(6).trim() : line}</span>
                  </li>
                );
              })}
            </ul>
          </div>
        )}
      </section>
    </div>
  );
}
