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
import type { ShapePart } from "../design";
import { circleTo, handlesOf, isFootprint, mirroredPart, movedPart, outlineProblem, partAt, partEdits, rectBetween, reshaped, shapeOf, snapTo, written } from "../design";
import type { Palette } from "../palette";
import { readPalette } from "../palette";
import type { PlanPicture, ShapePicture } from "../plan";
import { drawPlan, hitPart, robotExtent, SHAPE_HANDLE_PX } from "../plan";
import type { ConfigEdit, FieldConfig, PlacedIssue, RobotConfig } from "../protocol";
import { onThemeChange } from "../theme";
import type { View } from "../view";
import { fitView, pan, resize, toField, toScreen, zoomAt } from "../view";

export type Tool = "select" | "rect" | "circle" | "outline";

/** The Design view's drawing tools, and which part of the shape is selected. */
export interface DesignTools {
  tool: Tool;
  step: number; // what drawing snaps to, inches
  mirror: boolean; // a new part comes with its mirror image across the center line
  part: number | null; // the selected part of the shape
  onPart: (index: number | null) => void;
  onTool: (tool: Tool) => void;
  onStep: (step: number) => void;
  onMirror: (mirror: boolean) => void;
}

export const SNAP_STEPS: readonly (readonly [number, string])[] = [
  [0.125, "⅛ in"],
  [0.25, "¼ in"],
  [0.5, "½ in"],
  [1, "1 in"],
];

const TOOLS: readonly (readonly [Tool, string, string])[] = [
  ["select", "Select", "Pick and drag: parts of the shape (their corners reshape them), wheels, sensors, the CG"],
  ["rect", "Rectangle", "Drag from corner to corner"],
  ["circle", "Circle", "Drag from its center out"],
  ["outline", "Outline", "Click its corners; click the first one again (or press Enter) to close it"],
];

interface Drag {
  part: Part;
  turn: boolean;
  start: [number, number]; // where the pointer went down, in inches
  pointer: number;
  moved: Part | null; // the part where it's been dragged to (null: not yet)
}

/** A part of the shape being moved (handle null) or reshaped by one of its handles. */
interface Shaping {
  index: number;
  handle: number | null;
  start: [number, number];
  part: ShapePart;
  pointer: number;
  moved: ShapePart | null;
}

/** What's being drawn: its points so far (a rectangle's or circle's first), and the pointer. */
interface Sketch {
  tool: Tool;
  points: [number, number][];
  at: [number, number];
  pointer: number | null; // a rectangle or circle: the pointer drawing it
}

/** A robot (or field) drawn from its config. Drag a part to move it, its round handle to turn
 * it (Shift: finer steps), or use the arrow keys and [ ] on the selected part; each change
 * is written into the YAML in place. Wheel: zoom; drag the background: pan. With `design`,
 * the robot's shape is drawn and edited too: its parts selected, moved and reshaped, and new
 * ones drawn with the tools. */
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
  design?: DesignTools | null;
  onCopy?: () => void; // Ctrl+C: the selected part (a robot's)
  onPaste?: () => void; // Ctrl+V: a copy of what was copied
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
    let shaping: Shaping | null = null;
    let sketch: Sketch | null = null;
    let panning: { x: number; y: number; id: number } | null = null;
    let hovered: string | null = null;
    let hoveredPart: number | null = null;
    let pending = 0;
    /** A new config (or a change that failed): a dragged part is where the text says. */
    const settle = () => {
      drag = null;
      shaping = null;
      schedule();
    };
    /** The Design view's tools, when the robot can be edited by them just now. */
    const designing = (): DesignTools | null => {
      const p = live.current.props;
      return p.design && p.robot && !p.stale ? p.design : null;
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
    const shapePicture = (): ShapePicture | null => {
      const { props: p } = live.current;
      if (!p.design || !p.robot) return null;
      const shown = shapeOf(p.robot.body).map((part, i) => (shaping?.moved && shaping.index === i ? shaping.moved : part));
      let preview: ShapePart[] = [];
      if (sketch && sketch.tool !== "outline") {
        const made = sketch.tool === "rect" ? rectBetween(sketch.points[0], sketch.at) : circleTo(sketch.points[0], sketch.at, p.design.step);
        if (made) {
          const mirror = p.design.mirror ? mirroredPart(made) : null;
          preview = mirror ? [made, mirror] : [made];
        }
      }
      return {
        parts: shown,
        selected: p.design.part,
        hovered: hoveredPart,
        preview,
        sketch: sketch?.tool === "outline" ? [...sketch.points, sketch.at] : null,
        closing: !!sketch && sketch.tool === "outline" && closes(sketch),
      };
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
        design: shapePicture(),
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

    // --- the shape: drawing it, and its parts -------------------------------------------------

    const snapped = (point: [number, number], step: number): [number, number] => [snapTo(point[0], step), snapTo(point[1], step)];
    /** Whether the pointer is on an outline's first point (so a click there closes it). */
    function closes(s: Sketch): boolean {
      if (!view || s.points.length < 3) return false;
      const [fx, fy] = toScreen(view, ...s.points[0]);
      const [ax, ay] = toScreen(view, ...s.at);
      return Math.hypot(fx - ax, fy - ay) <= 8;
    }
    const sketchText = (s: Sketch, step: number): string => {
      if (s.tool === "outline") return `${s.points.length} point${s.points.length === 1 ? "" : "s"}: click the first again, or press Enter, to close it`;
      if (s.tool === "rect") {
        const made = rectBetween(s.points[0], s.at);
        return made ? `${made.size_in[0]} × ${made.size_in[1]} in` : "";
      }
      const made = circleTo(s.points[0], s.at, step);
      return made ? `⌀ ${made.diameter_in} in` : "";
    };
    /** New parts added to the shape (with their mirror images when mirroring), then selected. */
    const addParts = (made: ShapePart[], tools: DesignTools) => {
      const robot = live.current.props.robot!;
      const before = shapeOf(robot.body);
      const added = tools.mirror ? made.flatMap((part) => [part, ...[mirroredPart(part)].filter((m): m is ShapePart => !!m)]) : made;
      const edits: ConfigEdit[] = isFootprint(robot.body)
        ? [
            { location: "body.footprint_in", op: "remove" },
            { location: "body.shape", op: "set", value: [...before, ...added].map(written) },
          ]
        : added.map((part) => ({ location: "body.shape", op: "add", value: written(part) }));
      live.current.props
        .onEdits(edits)
        .then(() => {
          tools.onPart(before.length);
          tools.onTool("select");
        })
        .catch(() => {});
    };
    const finishOutline = (tools: DesignTools) => {
      if (!sketch) return;
      const problem = outlineProblem(sketch.points);
      if (problem) {
        show(`This outline can't close: ${problem}. Backspace takes the last point away.`);
        return;
      }
      const points = sketch.points;
      sketch = null;
      show("");
      addParts([{ type: "outline", points_in: points }], tools);
      schedule();
    };
    const removePart = (tools: DesignTools) => {
      const robot = live.current.props.robot!;
      const index = tools.part;
      if (index === null) return;
      if (shapeOf(robot.body).length <= 1) {
        show("A robot's shape needs a part: draw another before taking this one away.");
        return;
      }
      tools.onPart(null);
      live.current.props.onEdits(partEdits(robot, index, null)).catch(() => {});
    };
    const handleAt = (part: ShapePart, px: number, py: number): number | null => {
      if (!view) return null;
      const handles = handlesOf(part);
      for (let i = handles.length - 1; i >= 0; i--) {
        const [sx, sy] = toScreen(view, ...handles[i]);
        if (Math.abs(px - sx) <= SHAPE_HANDLE_PX + 3 && Math.abs(py - sy) <= SHAPE_HANDLE_PX + 3) return i;
      }
      return null;
    };

    // --- the pointer and the keys ---------------------------------------------------------------

    const onDown = (event: PointerEvent) => {
      if (!view || event.button !== 0) return;
      element.focus();
      const [px, py] = local(event);
      const point = toField(view, px, py);
      const { props: p, parts: current } = live.current;
      const tools = designing();
      if (tools && tools.tool !== "select") {
        const at = snapped(point, tools.step);
        if (tools.tool === "outline") {
          if (!sketch) sketch = { tool: "outline", points: [at], at, pointer: null };
          else if (closes(sketch)) finishOutline(tools);
          else {
            const last = sketch.points[sketch.points.length - 1];
            if (last[0] !== at[0] || last[1] !== at[1]) sketch.points.push(at);
          }
          if (sketch) show(sketchText(sketch, tools.step), event);
        } else {
          sketch = { tool: tools.tool, points: [at], at, pointer: event.pointerId };
          element.setPointerCapture(event.pointerId);
        }
        schedule();
        return;
      }
      if (tools && tools.part !== null) {
        const part = shapeOf(p.robot!.body)[tools.part];
        const handle = part ? handleAt(part, px, py) : null;
        if (part && handle !== null) {
          shaping = { index: tools.part, handle, start: point, part, pointer: event.pointerId, moved: null };
          element.setPointerCapture(event.pointerId);
          return;
        }
      }
      const hit = p.stale ? null : hitPart(current, view, px, py, p.selected);
      if (hit) {
        p.onSelect(hit.part);
        tools?.onPart(null);
        drag = { part: hit.part, turn: hit.turn, start: point, pointer: event.pointerId, moved: null };
        element.setPointerCapture(event.pointerId);
        return;
      }
      if (tools) {
        const shape = shapeOf(p.robot!.body);
        const index = partAt(shape, point[0], point[1], 3 / view.scale);
        tools.onPart(index);
        if (index !== null) {
          p.onSelect(null);
          shaping = { index, handle: null, start: point, part: shape[index], pointer: event.pointerId, moved: null };
          element.setPointerCapture(event.pointerId);
          schedule();
          return;
        }
      }
      panning = { x: event.clientX, y: event.clientY, id: event.pointerId };
      element.setPointerCapture(event.pointerId);
    };
    const onMove = (event: PointerEvent) => {
      if (!view) return;
      const [px, py] = local(event);
      const point = toField(view, px, py);
      const tools = designing();
      if (sketch && tools) {
        sketch.at = snapped(point, tools.step);
        show(sketchText(sketch, tools.step), event);
        schedule();
        return;
      }
      if (shaping && shaping.pointer === event.pointerId && tools) {
        const { part, handle, start } = shaping;
        if (handle === null) {
          shaping.moved = movedPart(part, snapTo(point[0] - start[0], tools.step), snapTo(point[1] - start[1], tools.step));
        } else {
          shaping.moved = reshaped(part, handle, point[0], point[1], tools.step);
        }
        const moved = shaping.moved;
        const [mx, my] = moved.type === "outline" ? [0, 0] : (moved.pos_in ?? [0, 0]);
        show(moved.type === "outline" ? `${moved.points_in.length} points` : moved.type === "rect" ? `${moved.size_in[0]} × ${moved.size_in[1]} in at ${mx}, ${my}` : `⌀ ${moved.diameter_in} in at ${mx}, ${my}`, event);
        schedule();
        return;
      }
      if (drag && drag.pointer === event.pointerId) {
        drag.moved = dragged(drag, point, event.shiftKey);
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
      let overPart: number | null = null;
      let overHandle = false;
      if (tools && !hit) {
        const shape = shapeOf(p.robot!.body);
        if (tools.part !== null && shape[tools.part]) overHandle = handleAt(shape[tools.part], px, py) !== null;
        overPart = tools.tool === "select" ? partAt(shape, point[0], point[1], 3 / view.scale) : null;
      }
      element.style.cursor =
        tools && tools.tool !== "select" ? "crosshair" : overHandle ? "nwse-resize" : !hit || p.stale ? (overPart !== null ? "move" : "") : hit.turn ? "crosshair" : "move";
      if (now !== hovered || overPart !== hoveredPart) {
        hovered = now;
        hoveredPart = overPart;
        schedule();
      }
    };
    const onUp = (event: PointerEvent) => {
      const tools = designing();
      if (sketch && sketch.pointer === event.pointerId) {
        const made = tools && sketch.tool === "rect" ? rectBetween(sketch.points[0], sketch.at) : tools ? circleTo(sketch.points[0], sketch.at, tools.step) : null;
        sketch = null;
        show("");
        if (made && tools) addParts([made], tools);
        schedule();
        return;
      }
      if (shaping && shaping.pointer === event.pointerId) {
        const { index, part, moved } = shaping;
        if (moved && tools && JSON.stringify(written(moved)) !== JSON.stringify(written(part))) {
          // drawn where it was dropped until the new text's config arrives (or the change fails)
          live.current.props.onEdits(partEdits(live.current.props.robot!, index, moved)).catch(settle);
        } else {
          shaping = null;
        }
        show("");
        return;
      }
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
      if (hovered !== null || hoveredPart !== null) {
        hovered = null;
        hoveredPart = null;
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
    const onDoubleClick = () => {
      const tools = designing();
      if (tools && sketch?.tool === "outline") finishOutline(tools);
      else if (!tools || tools.tool === "select") {
        fit();
        schedule();
      }
    };
    const onKey = (event: KeyboardEvent) => {
      const { props: p, parts: current, steps: step } = live.current;
      const tools = designing();
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
      const clip = { c: p.onCopy, v: p.onPaste }[event.key.toLowerCase()];
      if (mod && clip && p.robot && !event.shiftKey && !event.altKey) {
        event.preventDefault();
        clip();
        return;
      }
      if (sketch && tools) {
        if (event.key === "Escape") {
          sketch = null;
          show("");
        } else if (event.key === "Enter" && sketch.tool === "outline") finishOutline(tools);
        else if (event.key === "Backspace" && sketch.tool === "outline") {
          sketch.points.pop();
          if (!sketch.points.length) sketch = null;
          show(sketch ? sketchText(sketch, tools.step) : "");
        } else return;
        event.preventDefault();
        schedule();
        return;
      }
      if (event.key === "Escape") {
        p.onSelect(null);
        tools?.onPart(null);
        if (tools && tools.tool !== "select") tools.onTool("select");
        return;
      }
      if (tools && tools.part !== null && !p.selected && !mod && !event.altKey) {
        if (event.key === "Delete" || event.key === "Backspace") {
          event.preventDefault();
          removePart(tools);
          return;
        }
        const nudge: Record<string, [number, number]> = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, 1], ArrowDown: [0, -1] };
        const shape = shapeOf(p.robot!.body);
        if (event.key in nudge && shape[tools.part]) {
          event.preventDefault();
          const [dx, dy] = nudge[event.key];
          const moved = movedPart(shape[tools.part], dx * tools.step, dy * tools.step);
          p.onEdits(partEdits(p.robot!, tools.part, moved)).catch(() => {});
          return;
        }
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
    element.addEventListener("dblclick", onDoubleClick);
    element.addEventListener("keydown", onKey);
    const refit = () => {
      fit();
      schedule();
    };
    /** A tool picked: whatever was half drawn goes. */
    const retool = () => {
      sketch = null;
      show("");
      schedule();
    };
    container.addEventListener("vexsim:refit", refit);
    container.addEventListener("vexsim:settle", settle);
    container.addEventListener("vexsim:retool", retool);
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
      element.removeEventListener("dblclick", onDoubleClick);
      element.removeEventListener("keydown", onKey);
      container.removeEventListener("vexsim:refit", refit);
      container.removeEventListener("vexsim:settle", settle);
      container.removeEventListener("vexsim:retool", retool);
    };
  }, []);

  // redraw when what's drawn changes; a new config ends a drag
  useEffect(() => {
    box.current?.dispatchEvent(new Event("vexsim:settle"));
  }, [props.robot, props.field]);
  useEffect(() => {
    box.current?.dispatchEvent(new Event("vexsim:retool"));
  }, [props.design?.tool]);
  useEffect(() => {
    redraw.current();
  }, [props.issues, props.selected, props.stale, props.design?.part, props.design?.mirror, props.design?.step]);

  const kind = props.robot ? "robot" : "field";
  const design = props.design && props.robot ? props.design : null;
  return (
    <div className="diagram" ref={box}>
      <canvas
        ref={canvas}
        tabIndex={0}
        data-testid="diagram"
        role="img"
        aria-label={
          design
            ? "The robot, drawn from its config. Draw its shape with the tools; drag a part to move it, its corners to reshape it; Delete takes the selected part away; Ctrl+C and Ctrl+V copy and paste it."
            : `The ${kind}, drawn from its config. Drag a part to move it; arrow keys move the selected part, [ and ] turn it${props.robot ? "; Ctrl+C and Ctrl+V copy and paste it" : ""}.`
        }
      />
      <div className="readout-tip" ref={readout} hidden aria-live="polite" data-testid="drag-readout" />
      {design && (
        <div className="design-tools" role="toolbar" aria-label="Drawing tools" data-testid="design-tools">
          {TOOLS.map(([tool, label, hint]) => (
            <button
              key={tool}
              type="button"
              className={`small${design.tool === tool ? " on" : ""}`}
              aria-pressed={design.tool === tool}
              onClick={() => design.onTool(tool)}
              title={hint}
              data-testid={`tool-${tool}`}
            >
              {label}
            </button>
          ))}
          <label className="small" title="What drawing and dragging snap to">
            Snap{" "}
            <select value={design.step} onChange={(e) => design.onStep(Number(e.target.value))} data-testid="snap">
              {SNAP_STEPS.map(([step, label]) => (
                <option key={step} value={step}>
                  {label}
                </option>
              ))}
            </select>
          </label>
          <label className="small" title="Draw each new part with its mirror image across the robot's center line (left and right alike)">
            <input type="checkbox" checked={design.mirror} onChange={(e) => design.onMirror(e.target.checked)} data-testid="mirror" /> Mirror
          </label>
        </div>
      )}
      <div className="diagram-tools">
        <button type="button" className="ghost small" onClick={() => box.current?.dispatchEvent(new Event("vexsim:refit"))} title="Show it all (or double-click)">
          Fit
        </button>
      </div>
      {props.stale && <div className="hint">The YAML doesn't read just now: this is how it last did. Fix the text to drag again.</div>}
    </div>
  );
}
