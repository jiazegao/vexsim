import { useEffect, useRef } from "react";
import { frontOf } from "../body";
import { dot, drawElements, drawField, markFront, place, traceBody } from "../draw";
import type { Palette } from "../palette";
import { mix, readPalette, withAlpha } from "../palette";
import type { Preview, RouteRun, RouteStepData } from "../protocol";
import type { Dragged, Grip, LemPose, Motion, Planned, Point } from "../route";
import { bearing, isMotion, MOTION_INFO, numbersText, pointsOf, shortest, toVexsim } from "../route";
import { blockedBy } from "../startpose";
import { onThemeChange } from "../theme";
import type { View } from "../view";
import { fitView, pan, resize, toField, toScreen, zoomAt } from "../view";

const HANDLE_GAP_PX = 18; // from the robot's front to a heading handle
const HANDLE_PX = 7;
const MARKER_PX = 9;
const TURN_STEP = 15; // degrees a heading snaps to (1 with Shift)
const FINE_MOVE = 0.1; // inches, with Shift
const SPEED_SHADES = 16; // a trajectory's speed is drawn in this many shades

/** The steps that end in one place, as the field is drawn: one numbered marker. */
interface Marker {
  numbers: number[]; // from 1, in order
  at: Point; // where the first of them ends
}

/** Whether `steps[index]` has a target the field can drag (a point it goes to or faces). */
export function targetOf(step: RouteStepData | undefined): Point | null {
  if (!step || !isMotion(step.kind)) return null;
  const kind = MOTION_INFO[step.kind].target;
  return kind === "point" || kind === "pose" ? [step.target[0], step.target[1]] : null;
}

/** Whether `steps[index]` ends at a heading the field can turn. */
export function turnsTo(step: RouteStepData | undefined): boolean {
  return !!step && (step.kind === "turn_to_heading" || step.kind === "swing_to_heading" || step.kind === "move_to_pose");
}

/** What a step's end overlaps (the robot's outline there): field elements, or the walls. */
export function marksOf(planned: readonly Planned[], preview: Preview | null): string[][] {
  if (!preview) return planned.map(() => []);
  const field = { size: preview.field.size, obstacles: preview.field.obstacles };
  return planned.map((p) => blockedBy(toVexsim(p.pose), preview.robot, field));
}

/** A route on its field: where the robot starts (drag it, and its round handle, to move and
 * turn it), each step's planned end (its outline, numbered, joined to the one before by the
 * way there: vexsim's own motions' trajectories shaded by their planned speed), the selected
 * step's target, heading or a RAMSETE path's points to drag, and the last run's path and
 * ends beside the plan. With a motion tool, a click adds that step there. Wheel: zoom; drag
 * the background: pan; double-click: the whole field. */
export function RouteField(props: {
  preview: Preview | null;
  start: LemPose | null;
  steps: readonly RouteStepData[];
  planned: readonly Planned[];
  topSpeed: number | null; // in/s: the fastest a trajectory's shade says (null: the fastest planned)
  marks: readonly string[][];
  selected: number | null;
  run: RouteRun | null; // the last simulated run, if it's of this route as it is
  stale: boolean; // the drawn route isn't the text's just now
  snap: number; // inches a target snaps to
  tool: Motion | null;
  onSelect: (index: number | null) => void;
  onDrag: (dragged: Dragged | null) => void; // as it goes (null: over)
  onDrop: (dragged: Dragged) => void;
  onAdd: (kind: Motion, point: Point) => void;
}) {
  const box = useRef<HTMLDivElement>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  const readout = useRef<HTMLDivElement>(null);
  const live = useRef(props);
  live.current = props;
  const redraw = useRef<() => void>(() => {});

  useEffect(() => {
    const element = canvas.current!;
    const container = box.current!;
    const ctx = element.getContext("2d");
    if (!ctx) return;
    let view: View | null = null;
    let adjusted = false;
    let colors: Palette = readPalette();
    let drag: { grip: Grip; pointer: number; value: number[] | null } | null = null;
    let panning: { x: number; y: number; id: number } | null = null;
    let pending = 0;

    const size = (): [number, number] => live.current.preview?.field.size ?? [144, 144];
    const fit = () => {
      const [w, h] = size();
      view = fitView(w, h, container.clientWidth, container.clientHeight, 16);
      adjusted = false;
    };

    // --- drawing ------------------------------------------------------------------------------

    const robotAt = (pose: LemPose, stroke: string, fill: string, width: number, dash: number[] = []) => {
      const p = live.current;
      if (!p.preview) return;
      const drawn = toVexsim(pose);
      traceBody(ctx, view!, p.preview.robot, drawn);
      ctx.fillStyle = fill;
      ctx.fill();
      ctx.setLineDash(dash);
      ctx.strokeStyle = stroke;
      ctx.lineWidth = width;
      ctx.stroke();
      ctx.setLineDash([]);
      markFront(ctx, view!, p.preview.robot, drawn, width + 1.5);
    };
    const handleAt = (pose: LemPose): Point => {
      const p = live.current;
      const reach = (p.preview ? frontOf(p.preview.robot) : 7) + HANDLE_GAP_PX / view!.scale;
      const drawn = toVexsim(pose);
      return place(drawn, reach, 0);
    };
    const drawHandle = (pose: LemPose, on: boolean) => {
      const p = live.current;
      if (!p.preview) return;
      const drawn = toVexsim(pose);
      const [ex, ey] = toScreen(view!, ...place(drawn, frontOf(p.preview.robot), 0));
      const [hx, hy] = toScreen(view!, ...handleAt(pose));
      ctx.beginPath();
      ctx.moveTo(ex, ey);
      ctx.lineTo(hx, hy);
      ctx.strokeStyle = colors.ink2;
      ctx.lineWidth = 1.5;
      ctx.stroke();
      ctx.beginPath();
      ctx.arc(hx, hy, HANDLE_PX, 0, 2 * Math.PI);
      ctx.fillStyle = on ? colors.focus : colors.surface;
      ctx.fill();
      ctx.lineWidth = 2;
      ctx.strokeStyle = on ? colors.focus : colors.ink2;
      ctx.stroke();
    };
    const line = (points: readonly Point[], color: string, width: number, dash: number[] = []) => {
      if (points.length < 2) return;
      ctx.beginPath();
      points.forEach(([x, y], i) => {
        const [sx, sy] = toScreen(view!, x, y);
        if (i === 0) ctx.moveTo(sx, sy);
        else ctx.lineTo(sx, sy);
      });
      ctx.setLineDash(dash);
      ctx.strokeStyle = color;
      ctx.lineWidth = width;
      ctx.lineJoin = "round";
      ctx.stroke();
      ctx.setLineDash([]);
    };
    /** The fastest a trajectory's shade stands for (in/s). */
    const topSpeed = (): number => {
      const p = live.current;
      const fastest = Math.max(0, ...p.planned.flatMap((planned) => planned.speeds ?? []));
      return p.topSpeed && p.topSpeed > 0 ? Math.max(p.topSpeed, fastest) : fastest || 1;
    };
    /** A planned trajectory, each stretch in the shade of its speed (and the selected one on a
     * wash of the focus color). */
    const trajectory = (planned: Planned, on: boolean) => {
      const speeds = planned.speeds!;
      if (on) line(planned.path, withAlpha(colors.focus, 0.3), 9);
      const top = topSpeed();
      const shade = (k: number) => Math.round((Math.min(1, speeds[k] / top) || 0) * (SPEED_SHADES - 1));
      let first = 0; // a run of points in one shade, drawn as one line
      for (let k = 1; k < planned.path.length; k++) {
        if (k < planned.path.length - 1 && shade(k) === shade(first)) continue;
        line(planned.path.slice(first, k + 1), mix(colors.speedSlow, colors.speedFast, shade(first) / (SPEED_SHADES - 1)), on ? 3.5 : 2.5);
        first = k;
      }
    };
    /** The speed shades' key, in the field's lower left corner. */
    const speedKey = () => {
      const v = view!;
      const x = 14;
      const y = v.height - 16;
      const width = 90;
      ctx.font = "11px system-ui, -apple-system, 'Segoe UI', sans-serif";
      const range = `0 – ${Math.round(topSpeed())} in/s`;
      const gradient = ctx.createLinearGradient(x, 0, x + width, 0);
      gradient.addColorStop(0, colors.speedSlow);
      gradient.addColorStop(1, colors.speedFast);
      ctx.fillStyle = withAlpha(colors.surface, 0.92);
      ctx.beginPath();
      ctx.roundRect(x - 8, y - 26, width + ctx.measureText(range).width + 24, 36, 4);
      ctx.fill();
      ctx.fillStyle = gradient;
      ctx.fillRect(x, y - 4, width, 6);
      ctx.fillStyle = colors.ink2;
      ctx.textBaseline = "alphabetic";
      ctx.fillText("Planned speed", x, y - 11);
      ctx.fillText(range, x + width + 8, y + 3);
    };
    /** Where the steps end, a numbered marker for each place: the steps whose markers would
     * overlap as the field is drawn (turning or waiting where they are, or back where one was
     * before) share one. */
    const markers = (): Marker[] => {
      const p = live.current;
      const reach = (2 * MARKER_PX) / view!.scale; // inches: two nearer than this would overlap
      const found: Marker[] = [];
      p.planned.forEach((planned, i) => {
        const near = found.find((m) => Math.hypot(planned.pose[0] - m.at[0], planned.pose[1] - m.at[1]) < reach);
        if (near) near.numbers.push(i + 1);
        else found.push({ numbers: [i + 1], at: [planned.pose[0], planned.pose[1]] });
      });
      return found;
    };
    /** The step of a marker whose outline is drawn: the selected one, if it's one of them, else the last. */
    const shownOf = (marker: Marker): number => {
      const selected = live.current.selected;
      return selected !== null && marker.numbers.includes(selected + 1) ? selected : marker.numbers.at(-1)! - 1;
    };

    const draw = () => {
      pending = 0;
      const p = live.current;
      if (!view) fit();
      const v = view!;
      ctx.save();
      ctx.fillStyle = colors.page;
      ctx.fillRect(0, 0, v.width, v.height);
      const [w, h] = size();
      drawField(ctx, v, colors, [w, h]);
      if (p.preview) drawElements(ctx, v, colors, p.preview, p.preview.pieces);
      ctx.globalAlpha = p.stale ? 0.45 : 1;
      // the last run: the path it drove
      if (p.run?.path?.length) line(p.run.path.map(([, x, y]) => [x, y] as const), withAlpha(colors.truth, 0.8), 2);
      // the plan: the way to each step's end, and the robot's outline there
      let from: Point | null = p.start ? [p.start[0], p.start[1]] : null;
      p.planned.forEach((planned, i) => {
        const on = i === p.selected;
        if (from && planned.path.length > 1) {
          if (planned.speeds) trajectory(planned, on);
          else line(planned.path, on ? colors.focus : colors.target, on ? 3 : 2, planned.known ? [] : [5, 4]);
        }
        from = [planned.pose[0], planned.pose[1]];
      });
      // each step's end that moves or turns the robot, the selected one over the others
      const outline = (i: number) => {
        const planned = p.planned[i];
        const on = i === p.selected;
        const color = p.marks[i]?.length ? colors.critical : on ? colors.focus : colors.ink2;
        robotAt(planned.pose, color, withAlpha(color, on ? 0.12 : 0.05), on ? 2.5 : 1.25, planned.known || planned.ran ? [] : [4, 3]);
      };
      let before: LemPose | null = p.start;
      p.planned.forEach((planned, i) => {
        const changed = !before || Math.hypot(planned.pose[0] - before[0], planned.pose[1] - before[1]) > 0.05 || Math.abs(shortest(planned.pose[2] - before[2])) > 0.5;
        before = planned.pose;
        if (changed && i !== p.selected) outline(i);
      });
      if (p.selected !== null && p.planned[p.selected]) outline(p.selected);
      const ends = markers();
      // where the run's steps ended, beside where they were planned to
      p.run?.steps.forEach((step, i) => {
        const planned = p.planned[i];
        if (!step.pose || !planned) return;
        line([[planned.pose[0], planned.pose[1]], [step.pose[0], step.pose[1]]], withAlpha(colors.truth, 0.9), 1, [2, 2]);
        dot(ctx, v, step.pose[0], step.pose[1], 3.5, colors.truth, colors.surface);
      });
      // the selected step's target (a point it goes to or faces) and heading handle
      const index = p.selected;
      const step = index === null ? undefined : p.steps[index];
      const target = targetOf(step);
      const planned = index === null ? undefined : p.planned[index];
      if (target && planned) {
        const [tx, ty] = toScreen(v, target[0], target[1]);
        if (step!.kind === "turn_to_point" || step!.kind === "swing_to_point") {
          line([[planned.pose[0], planned.pose[1]], target], colors.focus, 1.5, [4, 4]);
        }
        ctx.beginPath();
        ctx.rect(tx - HANDLE_PX, ty - HANDLE_PX, 2 * HANDLE_PX, 2 * HANDLE_PX);
        ctx.fillStyle = drag?.grip.kind === "target" ? colors.focus : colors.surface;
        ctx.fill();
        ctx.strokeStyle = colors.focus;
        ctx.lineWidth = 2;
        ctx.stroke();
      }
      if (turnsTo(step) && planned) drawHandle(planned.pose, drag?.grip.kind === "heading");
      if (step?.kind === "ramsete" && index !== null) {
        // its points, joined from where it sets off, to drag
        const points = pointsOf(step);
        const setOff = index === 0 ? p.start : p.planned[index - 1]?.pose;
        if (setOff) line([[setOff[0], setOff[1]], ...points], withAlpha(colors.focus, 0.6), 1, [3, 3]);
        points.forEach((point, k) => {
          const [wx, wy] = toScreen(v, point[0], point[1]);
          const held = drag?.grip.kind === "waypoint" && drag.grip.point === k;
          ctx.beginPath();
          ctx.moveTo(wx, wy - HANDLE_PX - 1);
          ctx.lineTo(wx + HANDLE_PX + 1, wy);
          ctx.lineTo(wx, wy + HANDLE_PX + 1);
          ctx.lineTo(wx - HANDLE_PX - 1, wy);
          ctx.closePath();
          ctx.fillStyle = held ? colors.focus : colors.surface;
          ctx.fill();
          ctx.strokeStyle = colors.focus;
          ctx.lineWidth = 2;
          ctx.stroke();
        });
      }
      // the start: the robot itself, its heading handle
      if (p.start) {
        const blocked = p.preview ? blockedBy(toVexsim(p.start), p.preview.robot, { size: p.preview.field.size, obstacles: p.preview.field.obstacles }).length > 0 : false;
        robotAt(p.start, blocked ? colors.critical : colors.ink, withAlpha(blocked ? colors.critical : colors.ink, 0.1), 2);
        dot(ctx, v, p.start[0], p.start[1], 3, colors.ink);
        drawHandle(p.start, drag?.grip.kind === "start-heading");
      }
      if (p.planned.some((planned) => planned.speeds)) speedKey();
      // the step numbers, over everything
      ctx.font = "bold 11px system-ui, -apple-system, 'Segoe UI', sans-serif";
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      for (const end of ends) {
        const shown = shownOf(end);
        const pose = p.planned[shown].pose;
        const [sx, sy] = toScreen(v, pose[0], pose[1]);
        const on = p.selected === shown;
        const marked = end.numbers.some((n) => p.marks[n - 1]?.length > 0);
        const text = numbersText(end.numbers);
        const width = Math.max(2 * MARKER_PX, ctx.measureText(text).width + 8);
        ctx.beginPath();
        ctx.roundRect(sx - width / 2, sy - MARKER_PX, width, 2 * MARKER_PX, MARKER_PX);
        ctx.fillStyle = marked ? colors.critical : on ? colors.focus : colors.surface;
        ctx.fill();
        ctx.strokeStyle = marked ? colors.critical : on ? colors.focus : colors.ink2;
        ctx.lineWidth = 1.5;
        ctx.stroke();
        ctx.fillStyle = marked || on ? colors.surface : colors.ink;
        ctx.fillText(text, sx, sy + 0.5);
      }
      ctx.textAlign = "start";
      ctx.textBaseline = "alphabetic";
      ctx.globalAlpha = 1;
      ctx.restore();
      element.dataset.view = `${v.scale.toFixed(4)},${v.cx.toFixed(3)},${v.cy.toFixed(3)}`;
      element.dataset.markers = ends.map((e) => `${e.numbers.join("+")}@${p.planned[shownOf(e)].pose.map((n) => n.toFixed(2)).join(",")}`).join(" ");
      element.dataset.trajectories = p.planned.flatMap((planned, i) => (planned.speeds ? [`${i + 1}:${planned.seconds?.toFixed(2)}s`] : [])).join(" ");
    };
    const schedule = () => {
      if (!pending) pending = requestAnimationFrame(draw);
    };
    redraw.current = schedule;

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
      schedule();
    };
    const observer = new ResizeObserver(sizeCanvas);
    observer.observe(container);
    sizeCanvas();
    const stopTheme = onThemeChange(() => {
      colors = readPalette();
      schedule();
    });

    // --- the pointer ----------------------------------------------------------------------------

    const local = (event: PointerEvent | WheelEvent | MouseEvent): [number, number] => {
      const rect = element.getBoundingClientRect();
      return [event.clientX - rect.left, event.clientY - rect.top];
    };
    const near = (px: number, py: number, point: Point, radius: number) => {
      const [sx, sy] = toScreen(view!, point[0], point[1]);
      return Math.hypot(px - sx, py - sy) <= radius;
    };
    const show = (text: string, event?: PointerEvent) => {
      const tip = readout.current;
      if (!tip) return;
      tip.textContent = text;
      tip.hidden = !text;
      if (event) {
        const [px, py] = local(event);
        tip.style.left = `${px + 14}px`;
        tip.style.top = `${py + 14}px`;
      }
    };
    /** What a pointer at (px, py) grabs: the selected step's handles first, then the start's. */
    const gripAt = (px: number, py: number): Grip | null => {
      const p = live.current;
      const index = p.selected;
      if (index !== null) {
        const step = p.steps[index];
        const planned = p.planned[index];
        if (planned && turnsTo(step) && near(px, py, handleAt(planned.pose), HANDLE_PX + 4)) return { kind: "heading", index };
        if (step?.kind === "ramsete") {
          const points = pointsOf(step);
          for (let k = points.length - 1; k >= 0; k--) if (near(px, py, points[k], HANDLE_PX + 4)) return { kind: "waypoint", index, point: k };
        }
        const target = targetOf(step);
        if (target && near(px, py, target, HANDLE_PX + 4)) return { kind: "target", index };
      }
      if (p.start && near(px, py, handleAt(p.start), HANDLE_PX + 4)) return { kind: "start-heading" };
      if (p.start && near(px, py, [p.start[0], p.start[1]], 12)) return { kind: "start" };
      return null;
    };
    /** The step a click on a numbered marker at (px, py) selects, if there's one there: its
     * last step, or if one of its steps is selected, the one before that (round again). */
    const markerAt = (px: number, py: number): number | null => {
      const ends = markers();
      const p = live.current;
      for (let i = ends.length - 1; i >= 0; i--) {
        const pose = p.planned[shownOf(ends[i])].pose;
        if (!near(px, py, [pose[0], pose[1]], MARKER_PX + 3)) continue;
        const numbers = ends[i].numbers;
        const at = p.selected === null ? -1 : numbers.indexOf(p.selected + 1);
        return (at <= 0 ? numbers.at(-1)! : numbers[at - 1]) - 1;
      }
      return null;
    };
    const valueFor = (grip: Grip, point: Point, fine: boolean): number[] => {
      const p = live.current;
      const step = fine ? FINE_MOVE : p.snap;
      const snapTo = (v: number, s: number) => Number((Math.round(v / s) * s).toFixed(4)) + 0;
      const turn = (from: Point) => snapTo(bearing(from, point), fine ? 1 : TURN_STEP) % 360;
      if (grip.kind === "start") return [snapTo(point[0], step), snapTo(point[1], step), p.start![2]];
      if (grip.kind === "start-heading") return [p.start![0], p.start![1], turn([p.start![0], p.start![1]])];
      if (grip.kind === "target" || grip.kind === "waypoint") return [snapTo(point[0], step), snapTo(point[1], step)];
      const pose = p.planned[grip.index].pose;
      return [turn([pose[0], pose[1]])];
    };
    const describe = (dragged: Dragged): string => {
      const [a, b, c] = dragged.value;
      if (dragged.grip.kind === "start") return `start: (${a}, ${b})`;
      if (dragged.grip.kind === "start-heading") return `start: θ ${c}°`;
      if (dragged.grip.kind === "target") return `step ${dragged.grip.index + 1}: (${a}, ${b})`;
      if (dragged.grip.kind === "waypoint") return `step ${dragged.grip.index + 1}, point ${dragged.grip.point + 1}: (${a}, ${b})`;
      return `step ${dragged.grip.index + 1}: θ ${a}°`;
    };

    const onDown = (event: PointerEvent) => {
      if (!view || event.button !== 0) return;
      element.focus();
      const [px, py] = local(event);
      const p = live.current;
      const grip = p.stale ? null : gripAt(px, py);
      if (grip) {
        drag = { grip, pointer: event.pointerId, value: null };
        element.setPointerCapture(event.pointerId);
        schedule();
        return;
      }
      const marker = markerAt(px, py);
      if (marker !== null && !p.tool) {
        p.onSelect(marker);
        return;
      }
      if (p.tool && !p.stale) {
        const [x, y] = toField(view, px, py);
        const s = event.shiftKey ? FINE_MOVE : p.snap;
        p.onAdd(p.tool, [Number((Math.round(x / s) * s).toFixed(4)) + 0, Number((Math.round(y / s) * s).toFixed(4)) + 0]);
        return;
      }
      panning = { x: px, y: py, id: event.pointerId };
      element.setPointerCapture(event.pointerId);
    };
    const onMove = (event: PointerEvent) => {
      if (!view) return;
      const [px, py] = local(event);
      if (drag && drag.pointer === event.pointerId) {
        const value = valueFor(drag.grip, toField(view, px, py), event.shiftKey);
        drag.value = value;
        const dragged = { grip: drag.grip, value };
        live.current.onDrag(dragged);
        show(describe(dragged), event);
        return;
      }
      if (panning && panning.id === event.pointerId) {
        view = pan(view, px - panning.x, py - panning.y);
        adjusted = true;
        panning = { ...panning, x: px, y: py };
        schedule();
        return;
      }
      const p = live.current;
      const over = !p.stale && (gripAt(px, py) !== null || markerAt(px, py) !== null);
      element.style.cursor = over ? "pointer" : p.tool ? "crosshair" : "grab";
    };
    const onUp = (event: PointerEvent) => {
      if (drag && drag.pointer === event.pointerId) {
        const done = drag.value ? { grip: drag.grip, value: drag.value } : null;
        drag = null;
        show("");
        live.current.onDrag(null);
        if (done) live.current.onDrop(done);
        schedule();
      }
      if (panning && panning.id === event.pointerId) panning = null;
    };
    const onWheel = (event: WheelEvent) => {
      if (!view) return;
      event.preventDefault();
      const [px, py] = local(event);
      view = zoomAt(view, px, py, Math.exp(-event.deltaY * 0.0015));
      adjusted = true;
      schedule();
    };
    const onDouble = () => {
      fit();
      schedule();
    };
    element.addEventListener("pointerdown", onDown);
    element.addEventListener("pointermove", onMove);
    element.addEventListener("pointerup", onUp);
    element.addEventListener("pointercancel", onUp);
    element.addEventListener("wheel", onWheel, { passive: false });
    element.addEventListener("dblclick", onDouble);
    return () => {
      observer.disconnect();
      stopTheme();
      if (pending) cancelAnimationFrame(pending);
      element.removeEventListener("pointerdown", onDown);
      element.removeEventListener("pointermove", onMove);
      element.removeEventListener("pointerup", onUp);
      element.removeEventListener("pointercancel", onUp);
      element.removeEventListener("wheel", onWheel);
      element.removeEventListener("dblclick", onDouble);
    };
  }, []);

  useEffect(() => redraw.current());

  const p = props;
  return (
    <div className="diagram route-field" ref={box} data-testid="route-field">
      <canvas ref={canvas} tabIndex={0} aria-label="The route on its field: drag the start, and the selected step's target, heading or points" data-testid="route-canvas" />
      <div className="readout-tip" ref={readout} hidden aria-live="polite" data-testid="route-drag-readout" />
      {p.tool && <div className="hint">Click the field to add {p.tool === "ramsete" ? "a RAMSETE path to" : MOTION_INFO[p.tool].title.toLowerCase()} there (Esc: done)</div>}
      {!p.preview && <div className="hint">The robot or field doesn't read: fix the route's robot and field</div>}
    </div>
  );
}

