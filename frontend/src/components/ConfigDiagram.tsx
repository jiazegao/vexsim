import { useEffect, useMemo, useRef } from "react";
import type { Part, Steps } from "../configdoc";
import {
  FIELD_STEPS,
  fieldParts,
  issuesOf,
  moveEdits,
  ROBOT_STEPS,
  robotParts,
  snapAxis,
  snapHeading,
  turnEdits,
  wrapHeading,
} from "../configdoc";
import type { Palette } from "../palette";
import { readPalette } from "../palette";
import type { PlanPicture } from "../plan";
import { drawPlan, hitPart, robotExtent } from "../plan";
import type { ConfigEdit, FieldConfig, PlacedIssue, RobotConfig } from "../protocol";
import { onThemeChange } from "../theme";
import type { View } from "../view";
import { fitView, pan, resize, toField, zoomAt } from "../view";

interface Drag {
  part: Part;
  turn: boolean;
  start: [number, number]; // where the pointer went down, in inches
  pointer: number;
  moved: Part | null; // the part where it's been dragged to (null: not yet)
}

/** A robot (or field) drawn from its config. Drag a part to move it, its round handle to turn
 * it (Shift: finer steps), or use the arrow keys and [ ] on the selected part; each change
 * is written into the YAML in place. Wheel: zoom; drag the background: pan. */
export function ConfigDiagram(props: {
  robot: RobotConfig | null;
  field: FieldConfig | null;
  stale: boolean; // the text doesn't parse just now: this is how it last did
  issues: PlacedIssue[];
  selected: string | null;
  onSelect: (part: Part | null) => void;
  onEdits: (edits: ConfigEdit[]) => Promise<void>; // rejects if they couldn't be made
  onUndo: () => void;
  onRedo: () => void;
}) {
  const box = useRef<HTMLDivElement>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  const readout = useRef<HTMLDivElement>(null);
  const parts = useMemo(() => (props.robot ? robotParts(props.robot) : props.field ? fieldParts(props.field) : []), [props.robot, props.field]);
  const steps: Steps = props.robot ? ROBOT_STEPS : FIELD_STEPS;
  const live = useRef({ props, parts, steps });
  live.current = { props, parts, steps };
  const redraw = useRef<() => void>(() => {});

  useEffect(() => {
    const element = canvas.current!;
    const container = box.current!;
    const ctx = element.getContext("2d");
    if (!ctx) return;
    let view: View | null = null;
    let fittedTo = "";
    let adjusted = false;
    let colors: Palette = readPalette();
    let drag: Drag | null = null;
    let panning: { x: number; y: number; id: number } | null = null;
    let hovered: string | null = null;
    let pending = 0;
    /** A new config (or a change that failed): a dragged part is where the text says. */
    const settle = () => {
      drag = null;
      schedule();
    };

    const extent = (): [number, number] => {
      const { props: p, parts: current } = live.current;
      if (p.robot) return robotExtent(p.robot, current);
      return p.field?.size_in ?? [144, 144];
    };
    const fit = () => {
      const [w, h] = extent();
      view = fitView(w, h, container.clientWidth, container.clientHeight, 16);
      fittedTo = `${live.current.props.robot ? "robot" : "field"}`;
      adjusted = false;
    };
    const draw = () => {
      pending = 0;
      const { props: p, parts: current } = live.current;
      const kind = p.robot ? "robot" : "field";
      if (!view || (fittedTo !== kind && !adjusted)) fit();
      const shown = current.map((part) => (drag?.moved && drag.part.path === part.path ? drag.moved : part));
      const errors = new Set<string>();
      const warnings = new Set<string>();
      for (const part of current) {
        const found = issuesOf(part, p.issues);
        if (found.some((i) => i.severity === "error")) errors.add(part.path);
        else if (found.length) warnings.add(part.path);
      }
      const picture: PlanPicture = {
        robot: p.robot,
        field: p.robot ? null : p.field,
        parts: shown,
        selected: p.selected,
        hovered,
        errors,
        warnings,
        stale: p.stale,
      };
      drawPlan(ctx, view!, colors, picture);
      element.dataset.view = `${view!.scale.toFixed(4)},${view!.cx.toFixed(3)},${view!.cy.toFixed(3)}`;
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

    const local = (event: PointerEvent | WheelEvent | MouseEvent): [number, number] => {
      const rect = element.getBoundingClientRect();
      return [event.clientX - rect.left, event.clientY - rect.top];
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
    /** Where the part goes for a pointer at `point`. */
    const dragged = (d: Drag, point: [number, number], fine: boolean): Part => {
      const step = live.current.steps;
      if (d.turn) {
        const heading = snapHeading(point[0] - d.part.x, point[1] - d.part.y, fine ? step.fineTurn : step.turn);
        return { ...d.part, heading };
      }
      const move = fine ? step.fineMove : step.move;
      const x = snapAxis(d.part.x, point[0] - d.start[0], move);
      const y = snapAxis(d.part.y, point[1] - d.start[1], move);
      return { ...d.part, x, y };
    };
    const describe = (part: Part, turning: boolean) =>
      turning ? `${part.label}: ${part.heading}°` : `${part.label}: x ${part.x}  y ${part.y} in`;

    const onDown = (event: PointerEvent) => {
      if (!view || event.button !== 0) return;
      element.focus();
      const [px, py] = local(event);
      const { props: p, parts: current } = live.current;
      const hit = p.stale ? null : hitPart(current, view, px, py, p.selected);
      if (hit) {
        p.onSelect(hit.part);
        drag = { part: hit.part, turn: hit.turn, start: toField(view, px, py), pointer: event.pointerId, moved: null };
      } else {
        panning = { x: event.clientX, y: event.clientY, id: event.pointerId };
      }
      element.setPointerCapture(event.pointerId);
    };
    const onMove = (event: PointerEvent) => {
      if (!view) return;
      const [px, py] = local(event);
      if (drag && drag.pointer === event.pointerId) {
        drag.moved = dragged(drag, toField(view, px, py), event.shiftKey);
        show(describe(drag.moved, drag.turn), event);
        schedule();
        return;
      }
      if (panning && panning.id === event.pointerId) {
        view = pan(view, event.clientX - panning.x, event.clientY - panning.y);
        panning = { ...panning, x: event.clientX, y: event.clientY };
        adjusted = true;
        schedule();
        return;
      }
      const { props: p, parts: current } = live.current;
      const hit = hitPart(current, view, px, py, p.selected);
      const now = hit?.part.path ?? null;
      element.style.cursor = !hit || p.stale ? "" : hit.turn ? "crosshair" : "move";
      if (now !== hovered) {
        hovered = now;
        schedule();
      }
    };
    const onUp = (event: PointerEvent) => {
      if (drag && drag.pointer === event.pointerId) {
        const { part, moved, turn } = drag;
        if (moved && (moved.x !== part.x || moved.y !== part.y || moved.heading !== part.heading)) {
          // drawn where it was dropped until the new text's config arrives (or the change fails)
          live.current.props.onEdits(turn ? turnEdits(part, moved.heading ?? 0) : moveEdits(part, moved.x, moved.y)).catch(settle);
        } else {
          drag = null; // a click: just selected
        }
        show("");
      }
      if (panning && panning.id === event.pointerId) panning = null;
    };
    const onLeave = () => {
      if (hovered !== null) {
        hovered = null;
        schedule();
      }
    };
    const onWheel = (event: WheelEvent) => {
      if (!view) return;
      event.preventDefault();
      const [px, py] = local(event);
      view = zoomAt(view, px, py, Math.exp(-event.deltaY * 0.0015));
      adjusted = true;
      schedule();
    };
    const onKey = (event: KeyboardEvent) => {
      const { props: p, parts: current, steps: step } = live.current;
      const mod = event.ctrlKey || event.metaKey;
      if (mod && event.key.toLowerCase() === "z") {
        event.preventDefault();
        if (event.shiftKey) p.onRedo();
        else p.onUndo();
        return;
      }
      if (mod && event.key.toLowerCase() === "y") {
        event.preventDefault();
        p.onRedo();
        return;
      }
      if (event.key === "Escape") {
        p.onSelect(null);
        return;
      }
      const part = current.find((c) => c.path === p.selected);
      if (!part || p.stale || mod || event.altKey) return;
      const move = event.shiftKey ? step.fineMove : step.move;
      const turn = event.shiftKey ? step.fineTurn : step.turn;
      const nudge: Record<string, [number, number]> = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, 1], ArrowDown: [0, -1] };
      if (event.key in nudge) {
        event.preventDefault();
        const [dx, dy] = nudge[event.key];
        const x = dx ? snapAxis(part.x, dx * move, move) : part.x;
        const y = dy ? snapAxis(part.y, dy * move, move) : part.y;
        p.onEdits(moveEdits(part, x, y)).catch(() => {});
      } else if ((event.key === "[" || event.key === "]") && part.heading !== null) {
        event.preventDefault();
        const heading = wrapHeading(part.heading + (event.key === "]" ? turn : -turn));
        p.onEdits(turnEdits(part, heading)).catch(() => {});
      }
    };
    element.addEventListener("pointerdown", onDown);
    element.addEventListener("pointermove", onMove);
    element.addEventListener("pointerup", onUp);
    element.addEventListener("pointercancel", onUp);
    element.addEventListener("pointerleave", onLeave);
    element.addEventListener("wheel", onWheel, { passive: false });
    element.addEventListener("dblclick", fit);
    element.addEventListener("keydown", onKey);
    const refit = () => {
      fit();
      schedule();
    };
    container.addEventListener("vexsim:refit", refit);
    container.addEventListener("vexsim:settle", settle);
    return () => {
      cancelAnimationFrame(pending);
      observer.disconnect();
      stopTheme();
      element.removeEventListener("pointerdown", onDown);
      element.removeEventListener("pointermove", onMove);
      element.removeEventListener("pointerup", onUp);
      element.removeEventListener("pointercancel", onUp);
      element.removeEventListener("pointerleave", onLeave);
      element.removeEventListener("wheel", onWheel);
      element.removeEventListener("dblclick", fit);
      element.removeEventListener("keydown", onKey);
      container.removeEventListener("vexsim:refit", refit);
      container.removeEventListener("vexsim:settle", settle);
    };
  }, []);

  // redraw when what's drawn changes; a new config ends a drag
  useEffect(() => {
    box.current?.dispatchEvent(new Event("vexsim:settle"));
  }, [props.robot, props.field]);
  useEffect(() => {
    redraw.current();
  }, [props.issues, props.selected, props.stale]);

  const kind = props.robot ? "robot" : "field";
  return (
    <div className="diagram" ref={box}>
      <canvas
        ref={canvas}
        tabIndex={0}
        data-testid="diagram"
        role="img"
        aria-label={`The ${kind}, drawn from its config. Drag a part to move it; arrow keys move the selected part, [ and ] turn it.`}
      />
      <div className="readout-tip" ref={readout} hidden aria-live="polite" data-testid="drag-readout" />
      <div className="diagram-tools">
        <button type="button" className="ghost small" onClick={() => box.current?.dispatchEvent(new Event("vexsim:refit"))} title="Show it all (or double-click)">
          Fit
        </button>
      </div>
      {props.stale && <div className="hint">The YAML doesn't read just now: this is how it last did. Fix the text to drag again.</div>}
    </div>
  );
}
