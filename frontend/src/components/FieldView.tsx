import type { ReactNode } from "react";
import { useEffect, useRef, useState } from "react";
import type { Ghost, Layers, Picture, Shape, StartMarker } from "../draw";
import { draw, HANDLE_GAP_PX, HANDLE_RADIUS_PX } from "../draw";
import type { Palette } from "../palette";
import { readPalette } from "../palette";
import type { Playback } from "../playback";
import type { Playhead } from "../playhead";
import type { FrameMessage, Preview } from "../protocol";
import type { SessionStore } from "../session";
import type { Pose } from "../startpose";
import { blockedBy, FINE, hitStart, moved, SNAP, turned } from "../startpose";
import { onThemeChange } from "../theme";
import { Trail } from "../trail";
import type { View } from "../view";
import { fitView, pan, resize, toField, zoomAt } from "../view";

const NO_TRAIL = new Trail();
const HIT_SLOP_PX = 4; // the handle is easier to grab than it looks

export interface StartEdit {
  pose: Pose; // the run form's start
  editable: boolean; // false while a run is live
}

/** What the field shows: the live run, a recorded one at the playhead, or the robot and
 * field before any run. */
export type FieldSource =
  | { kind: "live"; store: SessionStore }
  | { kind: "recording"; playback: Playback; playhead: Playhead }
  | { kind: "preview" };

/** A recorded run drawn over the shown one, at the same moment. */
export interface Compared {
  playback: Playback;
  label: string;
  dash: readonly number[];
}

export interface FieldViewProps {
  source: FieldSource;
  compared: Compared[];
  preview: Preview | null;
  start: StartEdit | null;
  onStart: (pose: Pose) => void;
  layers: Layers;
  follow: boolean;
  onFollow: (follow: boolean) => void;
  stamp?: string | null; // written in the corner with the time, as when exporting a video
}

/** The field and the run on it, drawn every animation frame. Wheel: zoom; drag: pan, or
 * move the robot to its start (and turn it by its round handle); double-click: the
 * whole field again. */
export function FieldView(props: FieldViewProps) {
  const box = useRef<HTMLDivElement>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  const cursor = useRef<HTMLDivElement>(null);
  const live = useRef(props);
  live.current = props;
  const [grabbed, setGrabbed] = useState<StartMarker["grabbed"]>(null);
  const grabbedRef = useRef(grabbed);
  grabbedRef.current = grabbed;

  useEffect(() => {
    const element = canvas.current!;
    const container = box.current!;
    const ctx = element.getContext("2d");
    if (!ctx) return;
    let view: View | null = null;
    let fittedTo = "";
    let adjusted = false; // zoomed or panned by hand: keep that view on resize
    let colors: Palette = readPalette();
    let frameId = 0;
    let drag: { kind: "pan" | "move" | "rotate"; x: number; y: number; id: number; offset: [number, number] } | null = null;

    const shape = (): Shape | null => {
      const { source, preview } = live.current;
      if (source.kind === "live" && source.store.scene) return source.store.scene;
      if (source.kind === "recording") return source.playback.tape.scene;
      return preview ? { robot: preview.robot, field: preview.field } : null;
    };
    /** The run's frame now, and its time (null before any run). */
    const now = (): { frame: FrameMessage | null; t: number | null } => {
      const { source } = live.current;
      if (source.kind === "live") return { frame: source.store.frame, t: source.store.frame?.t ?? null };
      if (source.kind === "recording") {
        const t = source.playhead.t;
        return { frame: source.playback.frameAt(t), t };
      }
      return { frame: null, t: null };
    };
    const fieldSize = (): [number, number] => shape()?.field.size ?? [144, 144];
    const fit = () => {
      const [w, h] = fieldSize();
      view = fitView(w, h, container.clientWidth, container.clientHeight);
      fittedTo = `${w}x${h}`;
      adjusted = false;
    };
    const refit = () => {
      fit();
      live.current.onFollow(false);
    };

    const sizeCanvas = () => {
      const dpr = window.devicePixelRatio || 1;
      const width = container.clientWidth;
      const height = container.clientHeight;
      element.width = Math.max(1, Math.round(width * dpr));
      element.height = Math.max(1, Math.round(height * dpr));
      element.style.width = `${width}px`;
      element.style.height = `${height}px`;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      if (view && adjusted) view = resize(view, width, height);
      else fit();
    };

    /** The start marker, when there's a robot to drag. */
    const marker = (): StartMarker | null => {
      const { start, preview, source } = live.current;
      if (!start?.editable || !preview) return null;
      const blocked = blockedBy(start.pose, preview.robot.footprint, preview.field);
      const outline = source.kind === "recording" || (source.kind === "live" && !!source.store.frame);
      return { pose: start.pose, robot: preview.robot, outline, grabbed: grabbedRef.current, blocked };
    };

    const render = () => {
      frameId = requestAnimationFrame(render);
      const { source, preview, layers, follow, compared, stamp } = live.current;
      const [w, h] = fieldSize();
      if (!view || (fittedTo !== `${w}x${h}` && !adjusted)) fit();
      const { frame, t } = now();
      if (follow && frame) {
        view = { ...view!, cx: frame.pose[0], cy: frame.pose[1] };
        adjusted = true;
      }
      const ghosts: Ghost[] = [];
      if (t !== null) {
        for (const other of compared) {
          const at = other.playback.frameAt(t);
          if (at) ghosts.push({ label: other.label, dash: other.dash, robot: other.playback.tape.scene.robot, pose: at.pose, path: other.playback.trail("truth", t) });
        }
      }
      let picture: Picture;
      if (source.kind === "live" && source.store.scene) {
        const store = source.store;
        picture = { scene: store.scene, frame, overlay: store.overlay, truth: store.truth, estimate: store.estimate, start: marker(), ghosts };
      } else if (source.kind === "recording") {
        const { playback } = source;
        picture = {
          scene: playback.tape.scene,
          frame,
          overlay: playback.overlayAt(t ?? 0),
          truth: playback.trail("truth", t ?? 0),
          estimate: playback.trail("estimate", t ?? 0),
          start: marker(),
          ghosts,
        };
      } else {
        picture = { scene: shape(), frame: null, overlay: null, truth: NO_TRAIL, estimate: NO_TRAIL, pieces: preview?.pieces ?? [], start: marker() };
      }
      if (stamp && t !== null) picture.stamp = `${stamp} · ${t.toFixed(2)} s`;
      draw(ctx, view!, colors, picture, layers);
      // for tests and the curious: frames received, the time shown, the view (px per inch,
      // center), and how many compared runs are drawn
      element.dataset.frames = String(source.kind === "live" ? source.store.frames : 0);
      element.dataset.time = t === null ? "" : t.toFixed(3);
      element.dataset.view = `${view!.scale.toFixed(4)},${view!.cx.toFixed(3)},${view!.cy.toFixed(3)}`;
      element.dataset.ghosts = String(ghosts.length);
    };

    const observer = new ResizeObserver(sizeCanvas);
    observer.observe(container);
    sizeCanvas();
    render();
    const stopTheme = onThemeChange(() => {
      colors = readPalette();
    });

    const local = (event: PointerEvent | WheelEvent | MouseEvent): [number, number] => {
      const rect = element.getBoundingClientRect();
      return [event.clientX - rect.left, event.clientY - rect.top];
    };
    const grabAt = (point: [number, number]) => {
      const m = marker();
      if (!m || !view) return null;
      return hitStart(m.pose, m.robot.footprint, point, HANDLE_GAP_PX / view.scale, (HANDLE_RADIUS_PX + HIT_SLOP_PX) / view.scale);
    };
    const onWheel = (event: WheelEvent) => {
      if (!view) return;
      event.preventDefault();
      const [px, py] = local(event);
      view = zoomAt(view, px, py, Math.exp(-event.deltaY * 0.0015));
      adjusted = true;
    };
    const onDown = (event: PointerEvent) => {
      if (!view || event.button !== 0) return;
      const point = toField(view, ...local(event));
      const grab = grabAt(point);
      const m = marker();
      const offset: [number, number] = grab === "move" && m ? [m.pose[0] - point[0], m.pose[1] - point[1]] : [0, 0];
      drag = { kind: grab ?? "pan", x: event.clientX, y: event.clientY, id: event.pointerId, offset };
      if (grab) setGrabbed(grab);
      element.setPointerCapture(event.pointerId);
    };
    const onMove = (event: PointerEvent) => {
      if (!view) return;
      const point = toField(view, ...local(event));
      if (drag && drag.id === event.pointerId) {
        const m = marker();
        const step = event.shiftKey ? FINE : SNAP;
        if (drag.kind === "pan") {
          view = pan(view, event.clientX - drag.x, event.clientY - drag.y);
          drag = { ...drag, x: event.clientX, y: event.clientY };
          adjusted = true;
          if (live.current.follow) live.current.onFollow(false);
        } else if (m && drag.kind === "move") {
          const center: [number, number] = [point[0] + drag.offset[0], point[1] + drag.offset[1]];
          live.current.onStart(moved(m.pose, center, m.robot.footprint, fieldSize(), step));
        } else if (m && drag.kind === "rotate") {
          live.current.onStart(turned(m.pose, point, m.robot.footprint, fieldSize(), step));
        }
      } else {
        const grab = grabAt(point);
        element.style.cursor = grab === "move" ? "move" : grab === "rotate" ? "crosshair" : "";
      }
      if (cursor.current) {
        cursor.current.textContent = `x ${point[0].toFixed(1)}  y ${point[1].toFixed(1)} in`;
      }
    };
    const onUp = (event: PointerEvent) => {
      if (drag && drag.id === event.pointerId) {
        drag = null;
        setGrabbed(null);
      }
    };
    const onLeave = () => {
      if (cursor.current) cursor.current.textContent = "";
    };
    element.addEventListener("wheel", onWheel, { passive: false });
    element.addEventListener("pointerdown", onDown);
    element.addEventListener("pointermove", onMove);
    element.addEventListener("pointerup", onUp);
    element.addEventListener("pointercancel", onUp);
    element.addEventListener("pointerleave", onLeave);
    element.addEventListener("dblclick", refit);
    container.addEventListener("vexsim:fit", refit);
    return () => {
      cancelAnimationFrame(frameId);
      observer.disconnect();
      stopTheme();
      element.removeEventListener("wheel", onWheel);
      element.removeEventListener("pointerdown", onDown);
      element.removeEventListener("pointermove", onMove);
      element.removeEventListener("pointerup", onUp);
      element.removeEventListener("pointercancel", onUp);
      element.removeEventListener("pointerleave", onLeave);
      element.removeEventListener("dblclick", refit);
      container.removeEventListener("vexsim:fit", refit);
    };
  }, []);

  const { source, preview, start } = props;
  const store = source.kind === "live" ? source.store : null;
  const shownFrame = store ? store.frame : source.kind === "recording" ? source.playback.samples.length > 0 : null;
  let note: ReactNode = null;
  if (store && !store.scene) {
    note = store.state === "building" ? "Building the project…" : store.state === "error" ? "The run couldn't start: see the console below." : "Starting…";
  } else if (source.kind === "preview" && !preview) {
    note = (
      <>
        Pick a robot and a program, then press <b>Run</b>.
      </>
    );
  }
  const savePicture = () => {
    const element = canvas.current;
    if (!element) return;
    const scene = store?.scene ?? (source.kind === "recording" ? source.playback.tape.scene : preview);
    const robot = scene?.robot.name ?? "field";
    const shownTime = element.dataset.time ? Number(element.dataset.time) : null;
    const t = shownTime !== null ? `-${shownTime.toFixed(2)}s` : "";
    element.toBlob((blob) => {
      if (!blob) return;
      const link = document.createElement("a");
      link.href = URL.createObjectURL(blob);
      link.download = `vexsim-${robot.replace(/[^A-Za-z0-9._-]+/g, "_")}${t}.png`;
      link.click();
      setTimeout(() => URL.revokeObjectURL(link.href), 10_000);
    }, "image/png");
  };
  return (
    <div className="fieldview" ref={box}>
      <canvas
        ref={canvas}
        id="field-canvas"
        tabIndex={0}
        data-testid="field"
        aria-label="The field, seen from above. Keys drive the robot while a run is live."
        role="img"
      />
      <div className="fieldtools">
        <button
          type="button"
          className={`ghost small${props.follow ? " on" : ""}`}
          aria-pressed={props.follow}
          onClick={() => props.onFollow(!props.follow)}
          disabled={!shownFrame}
          title="Keep the robot in the middle of the view"
        >
          Follow
        </button>
        <button type="button" className="ghost small" onClick={() => box.current?.dispatchEvent(new Event("vexsim:fit"))} title="The whole field (or double-click it)">
          Fit
        </button>
        <button type="button" className="ghost small" onClick={savePicture} title="Save the field as it is now, as a PNG picture">
          Save picture
        </button>
      </div>
      <div className="cursor" ref={cursor} aria-hidden="true" />
      {note && (
        <div className="empty">
          <span>{note}</span>
        </div>
      )}
      {!note && start?.editable && preview && (
        <StartHint start={start} preview={preview} grabbed={!!grabbed} showingRun={!!shownFrame} />
      )}
    </div>
  );
}

function StartHint(props: { start: StartEdit; preview: Preview; grabbed: boolean; showingRun: boolean }) {
  const blocked = blockedBy(props.start.pose, props.preview.robot.footprint, props.preview.field);
  if (blocked.length) {
    return (
      <div className="hint bad" role="status" data-testid="start-blocked">
        The robot would start on top of {blocked.join(" and ")}: move it clear.
      </div>
    );
  }
  if (props.grabbed || props.showingRun) return null; // over a run, the dashed outline says it
  return (
    <div className="hint" aria-hidden="true">
      Drag the robot to where it starts; turn it by its round handle (Shift: finer).
    </div>
  );
}

/** A line in a compared run's dashes, for keys and legends. */
export function DashSwatch(props: { dash: readonly number[] }) {
  return (
    <svg className="dash" width="18" height="6" viewBox="0 0 18 6" aria-hidden="true">
      <line x1="0" y1="3" x2="18" y2="3" strokeDasharray={props.dash.join(" ")} />
    </svg>
  );
}

export interface KeyedRun {
  key: string;
  name: string;
  dash: readonly number[];
}

/** What the marks on the field mean, with switches for the ones that can be hidden, and the
 * runs drawn over this one. It sits in the field's corner, beside the field itself when the
 * view is wider than tall. */
export function FieldKey(props: { layers: Layers; onLayers: (layers: Layers) => void; compared: KeyedRun[]; onUncompare: (key: string) => void }) {
  const { layers } = props;
  const [open, setOpen] = useState(true);
  const row = (swatch: string, text: string, layer?: keyof Layers, title?: string) =>
    layer ? (
      <label className="keyrow" title={title}>
        <input type="checkbox" checked={layers[layer]} onChange={() => props.onLayers({ ...layers, [layer]: !layers[layer] })} />
        <i className={`swatch ${swatch}`} />
        {text}
      </label>
    ) : (
      <div className="keyrow">
        <span />
        <i className={`swatch ${swatch}`} />
        {text}
      </div>
    );
  return (
    <div className="fieldkey" role="group" aria-label="Key">
      <button type="button" className="keyhead" aria-expanded={open} onClick={() => setOpen(!open)}>
        Key <span aria-hidden="true">{open ? "▾" : "▸"}</span>
      </button>
      {open && (
        <>
          {row("robot", "Robot (front edge thicker)")}
          {row("line truth", "Where it went", "trails", "Show the paths (1)")}
          {row("line dashed estimate", "Where its code thinks it is", "estimate", "Show the robot code's estimate (2)")}
          {row("line dashed target", "Motion path / target")}
          {row("line beam", "Distance beams", "beams", "Show distance sensor beams (3)")}
          {row("line force", "Wheel side forces", "forces", "Show the sideways force on each wheel (4)")}
          {row("slip", "Wheel grip used")}
          {props.compared.length > 0 && <div className="keysub">Compared with</div>}
          {props.compared.map((run) => (
            <div className="keyrow" key={run.key} data-testid="compared-key">
              <button type="button" className="unkey" onClick={() => props.onUncompare(run.key)} title={`Stop drawing ${run.name}`} aria-label={`Stop comparing with ${run.name}`}>
                ×
              </button>
              <DashSwatch dash={run.dash} />
              <span className="keyname" title={run.name}>
                {run.name}
              </span>
            </div>
          ))}
        </>
      )}
    </div>
  );
}
